#!/usr/bin/env python3
"""Outbound SSH/file/VNC bridge for DevicesWebControl.

The agent never opens a new public listening port. It connects to the platform
and multiplexes local OpenSSH, a restricted home-directory file API, and the
loopback VNC service over one authenticated WebSocket.
"""

import argparse
import asyncio
import configparser
import errno
import fcntl
import inspect
import json
import logging
import os
import posixpath
import pty
import re
import shutil
import signal
import socket
import stat
import struct
import subprocess
import tempfile
import termios
import time
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional, Tuple

import websockets


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_FILE = SCRIPT_DIR / "iot_client.conf"
BINARY_HEADER = struct.Struct("!I")
SSH_USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,63}$", re.IGNORECASE)

REMOTE_ROOT = Path(os.environ.get("DWC_REMOTE_ROOT", str(Path.home()))).expanduser().resolve()
SSH_HOST = "127.0.0.1"
SSH_PORT = int(os.environ.get("DWC_REMOTE_SSH_PORT", "22"))
VNC_HOST = "127.0.0.1"
VNC_PORT = int(os.environ.get("DWC_REMOTE_VNC_PORT", "5900"))
MAX_UPLOAD_BYTES = int(os.environ.get("DWC_REMOTE_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
FILE_CHUNK_BYTES = 64 * 1024
WEBSOCKET_MAX_MESSAGE_BYTES = 8 * 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("remote_access_agent")


class AgentOperationError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def load_config(config_path: Path) -> Tuple[str, str]:
    parser = configparser.ConfigParser()
    parser.read(str(config_path), encoding="utf-8")
    server = parser.get("client", "server", fallback="").strip().rstrip("/")
    token = parser.get("client", "token", fallback="").strip()
    if not server:
        raise RuntimeError("未在 {} 中配置 server".format(config_path))
    if not token or token == "YOUR_DEVICE_TOKEN_HERE":
        raise RuntimeError("未在 {} 中配置有效 token".format(config_path))
    return server, token


def websocket_url(server: str) -> str:
    parsed = urllib.parse.urlsplit(server)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError("无效的服务器地址: {}".format(server))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/") + "/api/agent/ws/remote-access"
    return urllib.parse.urlunsplit((scheme, parsed.netloc, path, "", ""))


def websocket_connect_kwargs(token: str) -> Dict[str, Any]:
    parameters = inspect.signature(websockets.connect).parameters
    kwargs = {
        "close_timeout": 2,
        "max_size": WEBSOCKET_MAX_MESSAGE_BYTES,
        "ping_interval": 20,
        "ping_timeout": 20,
    }
    headers = {"X-Device-Token": token}
    if "additional_headers" in parameters:
        kwargs["additional_headers"] = headers
    else:
        kwargs["extra_headers"] = headers
    if "open_timeout" in parameters:
        kwargs["open_timeout"] = 10
    elif "timeout" in parameters:
        kwargs["timeout"] = 10
    return kwargs


def port_is_open(host: str, port: int) -> bool:
    try:
        connection = socket.create_connection((host, port), timeout=0.4)
        connection.close()
        return True
    except OSError:
        return False


def _is_within_root(path: Path) -> bool:
    try:
        return os.path.commonpath((str(REMOTE_ROOT), str(path))) == str(REMOTE_ROOT)
    except ValueError:
        return False


def _virtual_parts(value: str) -> Tuple[Tuple[str, ...], str]:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise AgentOperationError("文件路径无效", 400)
    value = value.replace("\\", "/")
    raw_parts = PurePosixPath("/" + value.lstrip("/")).parts
    if ".." in raw_parts:
        raise AgentOperationError("不允许访问文件根目录之外的路径", 403)
    parts = tuple(part for part in raw_parts if part not in ("/", "", "."))
    virtual = "/" + "/".join(parts)
    return parts, virtual


def resolve_virtual_path(
    value: str,
    *,
    must_exist: bool = True,
    follow_final: bool = True,
) -> Tuple[Path, str]:
    parts, virtual = _virtual_parts(value)
    candidate = REMOTE_ROOT.joinpath(*parts)
    if follow_final:
        try:
            resolved = candidate.resolve(strict=must_exist)
        except FileNotFoundError:
            raise AgentOperationError("文件或目录不存在", 404)
        if not _is_within_root(resolved):
            raise AgentOperationError("不允许访问文件根目录之外的路径", 403)
        return resolved, virtual

    if candidate == REMOTE_ROOT:
        return REMOTE_ROOT, virtual
    try:
        parent = candidate.parent.resolve(strict=True)
    except FileNotFoundError:
        raise AgentOperationError("父目录不存在", 404)
    if not _is_within_root(parent):
        raise AgentOperationError("不允许访问文件根目录之外的路径", 403)
    lexical = parent / candidate.name
    if must_exist and not os.path.lexists(str(lexical)):
        raise AgentOperationError("文件或目录不存在", 404)
    return lexical, virtual


def file_entry(parent_virtual: str, entry: os.DirEntry) -> Dict[str, Any]:
    info = entry.stat(follow_symlinks=False)
    if stat.S_ISDIR(info.st_mode):
        entry_type = "directory"
    elif stat.S_ISREG(info.st_mode):
        entry_type = "file"
    elif stat.S_ISLNK(info.st_mode):
        entry_type = "symlink"
    else:
        entry_type = "other"
    path = posixpath.join(parent_virtual.rstrip("/") or "/", entry.name)
    if not path.startswith("/"):
        path = "/" + path
    return {
        "name": entry.name,
        "path": path,
        "type": entry_type,
        "size": int(info.st_size),
        "modified": int(info.st_mtime * 1000),
        "permissions": stat.filemode(info.st_mode),
        "readable": os.access(entry.path, os.R_OK),
        "writable": os.access(entry.path, os.W_OK),
        "hidden": entry.name.startswith("."),
    }


def handle_file_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if action == "file_list":
        directory, virtual = resolve_virtual_path(str(payload.get("path") or "/"))
        if not directory.is_dir():
            raise AgentOperationError("目标不是目录", 400)
        entries = []
        with os.scandir(str(directory)) as iterator:
            for entry in iterator:
                try:
                    entries.append(file_entry(virtual, entry))
                except (FileNotFoundError, PermissionError):
                    continue
        entries.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
        return {
            "path": virtual,
            "root": str(REMOTE_ROOT),
            "entries": entries,
        }

    if action == "file_mkdir":
        target, virtual = resolve_virtual_path(
            str(payload.get("path") or ""),
            must_exist=False,
            follow_final=False,
        )
        if target == REMOTE_ROOT:
            raise AgentOperationError("不能创建或覆盖文件根目录", 400)
        if os.path.lexists(str(target)):
            raise AgentOperationError("同名文件或目录已存在", 409)
        target.mkdir(mode=0o755)
        return {"ok": True, "path": virtual}

    if action == "file_rename":
        source, source_virtual = resolve_virtual_path(
            str(payload.get("source") or ""),
            follow_final=False,
        )
        destination, destination_virtual = resolve_virtual_path(
            str(payload.get("destination") or ""),
            must_exist=False,
            follow_final=False,
        )
        if source == REMOTE_ROOT or destination == REMOTE_ROOT:
            raise AgentOperationError("不能重命名文件根目录", 400)
        if os.path.lexists(str(destination)):
            raise AgentOperationError("目标名称已存在", 409)
        source.rename(destination)
        return {"ok": True, "source": source_virtual, "destination": destination_virtual}

    if action == "file_delete":
        target, virtual = resolve_virtual_path(
            str(payload.get("path") or ""),
            follow_final=False,
        )
        if target == REMOTE_ROOT:
            raise AgentOperationError("不能删除文件根目录", 400)
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            try:
                target.rmdir()
            except OSError as exc:
                if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
                    raise AgentOperationError("目录非空，为避免误删不执行递归删除", 409)
                raise
        else:
            raise AgentOperationError("暂不支持删除此文件类型", 400)
        return {"ok": True, "path": virtual}

    raise AgentOperationError("未知文件操作", 400)


def operation_error(exc: BaseException) -> Tuple[int, str]:
    if isinstance(exc, AgentOperationError):
        return exc.status, str(exc)
    if isinstance(exc, PermissionError):
        return 403, "当前车端用户没有所需文件权限"
    if isinstance(exc, FileNotFoundError):
        return 404, "文件或目录不存在"
    if isinstance(exc, FileExistsError):
        return 409, "同名文件或目录已存在"
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return 507, "车端磁盘空间不足"
        if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
            return 409, "目录非空或目标已存在"
    return 500, str(exc) or exc.__class__.__name__


class BaseStream:
    def __init__(self, agent: "RemoteAccessAgent", stream_id: int) -> None:
        self.agent = agent
        self.stream_id = stream_id
        self.task = None  # type: Optional[asyncio.Task]

    async def start(self) -> Dict[str, Any]:
        return {}

    def launch(self) -> None:
        return None

    async def feed(self, data: bytes) -> None:
        raise AgentOperationError("该远程流不接受输入", 400)

    async def control(self, action: str, payload: Dict[str, Any]) -> None:
        return None

    async def close(self, commit: bool = False) -> Dict[str, Any]:
        return {}

    async def _cancel_task(self) -> None:
        if self.task is not None and self.task is not asyncio.current_task() and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class SshStream(BaseStream):
    def __init__(self, agent: "RemoteAccessAgent", stream_id: int, params: Dict[str, Any]) -> None:
        super().__init__(agent, stream_id)
        self.username = str(params.get("username") or os.environ.get("USER") or "wheeltec")
        self.cols = max(20, min(500, int(params.get("cols") or 120)))
        self.rows = max(5, min(300, int(params.get("rows") or 32)))
        self.master_fd = None  # type: Optional[int]
        self.process = None  # type: Optional[subprocess.Popen]

    @staticmethod
    def _set_window_size(fd: int, rows: int, cols: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def start(self) -> Dict[str, Any]:
        if not SSH_USERNAME_PATTERN.fullmatch(self.username):
            raise AgentOperationError("SSH 用户名格式无效", 400)
        ssh_binary = shutil.which("ssh")
        if not ssh_binary:
            raise AgentOperationError("车端未安装 OpenSSH 客户端", 503)
        if not port_is_open(SSH_HOST, SSH_PORT):
            raise AgentOperationError("车端 OpenSSH 服务未监听", 503)
        master_fd, slave_fd = pty.openpty()
        self._set_window_size(slave_fd, self.rows, self.cols)
        command = [
            ssh_binary,
            "-tt",
            "-p", str(SSH_PORT),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "LogLevel=ERROR",
            "{}@{}".format(self.username, SSH_HOST),
        ]

        def prepare_pty_child() -> None:
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        try:
            self.process = subprocess.Popen(
                command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                preexec_fn=prepare_pty_child,
            )
        finally:
            os.close(slave_fd)
        self.master_fd = master_fd
        return {
            "username": self.username,
            "host": SSH_HOST,
            "port": SSH_PORT,
            "cols": self.cols,
            "rows": self.rows,
        }

    def launch(self) -> None:
        self.task = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            while self.master_fd is not None:
                try:
                    data = await loop.run_in_executor(None, os.read, self.master_fd, FILE_CHUNK_BYTES)
                except OSError as exc:
                    if exc.errno in (errno.EIO, errno.EBADF):
                        break
                    raise
                if not data:
                    break
                await self.agent.send_binary(self.stream_id, data)
            exit_code = self.process.poll() if self.process is not None else None
            await self.agent.complete_stream(self, result={"exit_code": exit_code})
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await self.agent.complete_stream(self, error=operation_error(exc)[1])

    async def feed(self, data: bytes) -> None:
        if self.master_fd is None:
            raise AgentOperationError("SSH 会话已关闭", 410)
        offset = 0
        while offset < len(data):
            offset += os.write(self.master_fd, data[offset:])

    async def control(self, action: str, payload: Dict[str, Any]) -> None:
        if action != "resize" or self.master_fd is None:
            return
        self.cols = max(20, min(500, int(payload.get("cols") or self.cols)))
        self.rows = max(5, min(300, int(payload.get("rows") or self.rows)))
        self._set_window_size(self.master_fd, self.rows, self.cols)

    async def close(self, commit: bool = False) -> Dict[str, Any]:
        fd, self.master_fd = self.master_fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        process = self.process
        if process is not None and process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
            loop = asyncio.get_event_loop()
            deadline = loop.time() + 2.0
            while process.poll() is None and loop.time() < deadline:
                await asyncio.sleep(0.05)
            if process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                await loop.run_in_executor(None, process.wait)
        await self._cancel_task()
        return {"exit_code": process.poll() if process is not None else None}


class VncStream(BaseStream):
    def __init__(self, agent: "RemoteAccessAgent", stream_id: int) -> None:
        super().__init__(agent, stream_id)
        self.reader = None
        self.writer = None

    async def start(self) -> Dict[str, Any]:
        try:
            self.reader, self.writer = await asyncio.open_connection(VNC_HOST, VNC_PORT)
        except OSError:
            raise AgentOperationError("车端 VNC 服务未监听 {}:{}".format(VNC_HOST, VNC_PORT), 503)
        return {"host": VNC_HOST, "port": VNC_PORT}

    def launch(self) -> None:
        self.task = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            while self.reader is not None:
                data = await self.reader.read(FILE_CHUNK_BYTES)
                if not data:
                    break
                await self.agent.send_binary(self.stream_id, data)
            await self.agent.complete_stream(self)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await self.agent.complete_stream(self, error=operation_error(exc)[1])

    async def feed(self, data: bytes) -> None:
        if self.writer is None:
            raise AgentOperationError("VNC 会话已关闭", 410)
        self.writer.write(data)
        await self.writer.drain()

    async def close(self, commit: bool = False) -> Dict[str, Any]:
        writer, self.writer = self.writer, None
        self.reader = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (AttributeError, OSError):
                pass
        await self._cancel_task()
        return {}


class FileReadStream(BaseStream):
    def __init__(self, agent: "RemoteAccessAgent", stream_id: int, params: Dict[str, Any]) -> None:
        super().__init__(agent, stream_id)
        self.path_value = str(params.get("path") or "")
        self.file = None
        self.virtual = ""

    async def start(self) -> Dict[str, Any]:
        path, self.virtual = resolve_virtual_path(self.path_value)
        if not path.is_file():
            raise AgentOperationError("目标不是普通文件", 400)
        self.file = path.open("rb")
        info = path.stat()
        return {"name": path.name, "path": self.virtual, "size": int(info.st_size)}

    def launch(self) -> None:
        self.task = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_event_loop()
        sent = 0
        try:
            while self.file is not None:
                data = await loop.run_in_executor(None, self.file.read, FILE_CHUNK_BYTES)
                if not data:
                    break
                sent += len(data)
                await self.agent.send_binary(self.stream_id, data)
            await self.agent.complete_stream(self, result={"path": self.virtual, "bytes": sent})
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await self.agent.complete_stream(self, error=operation_error(exc)[1])

    async def close(self, commit: bool = False) -> Dict[str, Any]:
        file_handle, self.file = self.file, None
        if file_handle is not None:
            file_handle.close()
        await self._cancel_task()
        return {}


class FileWriteStream(BaseStream):
    def __init__(self, agent: "RemoteAccessAgent", stream_id: int, params: Dict[str, Any]) -> None:
        super().__init__(agent, stream_id)
        self.path_value = str(params.get("path") or "")
        self.overwrite = bool(params.get("overwrite"))
        self.declared_size = params.get("size")
        self.destination = None  # type: Optional[Path]
        self.virtual = ""
        self.temp_path = None  # type: Optional[Path]
        self.file = None
        self.received = 0
        self.mode = 0o644

    async def start(self) -> Dict[str, Any]:
        destination, self.virtual = resolve_virtual_path(
            self.path_value,
            must_exist=False,
            follow_final=False,
        )
        if destination == REMOTE_ROOT:
            raise AgentOperationError("不能覆盖文件根目录", 400)
        if destination.exists() and destination.is_dir():
            raise AgentOperationError("目标路径是目录", 409)
        if os.path.lexists(str(destination)) and not self.overwrite:
            raise AgentOperationError("同名文件已存在", 409)
        if isinstance(self.declared_size, int) and self.declared_size > MAX_UPLOAD_BYTES:
            raise AgentOperationError("上传文件超过车端允许的大小", 413)
        if isinstance(self.declared_size, int):
            free = shutil.disk_usage(str(destination.parent)).free
            if self.declared_size > free:
                raise AgentOperationError("车端磁盘空间不足", 507)
        if destination.exists():
            self.mode = stat.S_IMODE(destination.stat().st_mode)
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".dwc-upload-",
            dir=str(destination.parent),
            delete=False,
        )
        self.destination = destination
        self.temp_path = Path(handle.name)
        self.file = handle
        return {"name": destination.name, "path": self.virtual}

    async def feed(self, data: bytes) -> None:
        if self.file is None:
            raise AgentOperationError("上传流已关闭", 410)
        self.received += len(data)
        if self.received > MAX_UPLOAD_BYTES:
            raise AgentOperationError("上传文件超过车端允许的大小", 413)
        self.file.write(data)

    async def close(self, commit: bool = False) -> Dict[str, Any]:
        file_handle, self.file = self.file, None
        temp_path, self.temp_path = self.temp_path, None
        try:
            if file_handle is not None:
                if commit:
                    file_handle.flush()
                    os.fsync(file_handle.fileno())
                    os.fchmod(file_handle.fileno(), self.mode)
                file_handle.close()
            if temp_path is None:
                return {}
            if not commit:
                temp_path.unlink(missing_ok=True)
                return {}
            if self.destination is None:
                raise AgentOperationError("上传目标路径无效", 400)
            if os.path.lexists(str(self.destination)) and not self.overwrite:
                raise AgentOperationError("同名文件已存在", 409)
            os.replace(str(temp_path), str(self.destination))
            return {"path": self.virtual, "bytes": self.received, "name": self.destination.name}
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise


class RemoteAccessAgent:
    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token
        self.websocket = None
        self.send_lock = asyncio.Lock()
        self.streams = {}  # type: Dict[int, BaseStream]

    async def send_json(self, message: Dict[str, Any]) -> None:
        if self.websocket is None:
            raise ConnectionError("远程访问 WebSocket 未连接")
        async with self.send_lock:
            await self.websocket.send(json.dumps(message, separators=(",", ":"), ensure_ascii=False))

    async def send_binary(self, stream_id: int, data: bytes) -> None:
        if self.websocket is None:
            raise ConnectionError("远程访问 WebSocket 未连接")
        packet = BINARY_HEADER.pack(stream_id) + data
        async with self.send_lock:
            await self.websocket.send(packet)

    def capabilities(self) -> Dict[str, Any]:
        return {
            "protocol": 1,
            "user": os.environ.get("USER") or Path.home().name,
            "files": {
                "available": REMOTE_ROOT.is_dir(),
                "root": str(REMOTE_ROOT),
                "max_upload_bytes": MAX_UPLOAD_BYTES,
            },
            "ssh": {
                "available": shutil.which("ssh") is not None and port_is_open(SSH_HOST, SSH_PORT),
                "host": SSH_HOST,
                "port": SSH_PORT,
            },
            "vnc": {
                "available": port_is_open(VNC_HOST, VNC_PORT),
                "host": VNC_HOST,
                "port": VNC_PORT,
            },
        }

    async def handle_request(self, message: Dict[str, Any]) -> None:
        request_id = message.get("id")
        if not isinstance(request_id, int):
            return
        action = str(message.get("action") or "")
        payload = message.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, handle_file_action, action, payload)
            response = {"type": "response", "id": request_id, "ok": True, "result": result}
        except Exception as exc:
            status, error = operation_error(exc)
            response = {
                "type": "response",
                "id": request_id,
                "ok": False,
                "status": status,
                "error": error,
            }
        await self.send_json(response)

    async def handle_stream_open(self, message: Dict[str, Any]) -> None:
        stream_id = message.get("id")
        if not isinstance(stream_id, int) or stream_id <= 0:
            return
        if stream_id in self.streams:
            await self.send_json({
                "type": "stream_error",
                "id": stream_id,
                "status": 409,
                "error": "远程流 ID 已存在",
            })
            return
        kind = str(message.get("kind") or "")
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}
        stream = None
        try:
            if kind == "ssh":
                stream = SshStream(self, stream_id, params)
            elif kind == "vnc":
                stream = VncStream(self, stream_id)
            elif kind == "file_read":
                stream = FileReadStream(self, stream_id, params)
            elif kind == "file_write":
                stream = FileWriteStream(self, stream_id, params)
            else:
                raise AgentOperationError("未知远程流类型", 400)
            self.streams[stream_id] = stream
            metadata = await stream.start()
            await self.send_json({"type": "stream_opened", "id": stream_id, "meta": metadata})
            stream.launch()
        except Exception as exc:
            self.streams.pop(stream_id, None)
            if stream is not None:
                try:
                    await stream.close(False)
                except Exception:
                    pass
            status, error = operation_error(exc)
            await self.send_json({
                "type": "stream_error",
                "id": stream_id,
                "status": status,
                "error": error,
            })

    async def handle_stream_control(self, message: Dict[str, Any]) -> None:
        stream_id = message.get("id")
        stream = self.streams.get(stream_id) if isinstance(stream_id, int) else None
        if stream is None:
            return
        payload = message.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        try:
            await stream.control(str(message.get("action") or ""), payload)
        except Exception as exc:
            await self.complete_stream(stream, error=operation_error(exc)[1])

    async def handle_stream_close(self, message: Dict[str, Any]) -> None:
        stream_id = message.get("id")
        stream = self.streams.pop(stream_id, None) if isinstance(stream_id, int) else None
        if stream is None:
            return
        try:
            result = await stream.close(bool(message.get("commit")))
            await self.send_json({
                "type": "stream_closed",
                "id": stream_id,
                "ok": True,
                "result": result,
            })
        except Exception as exc:
            status, error = operation_error(exc)
            await self.send_json({
                "type": "stream_closed",
                "id": stream_id,
                "ok": False,
                "status": status,
                "error": error,
            })

    async def handle_binary(self, packet: bytes) -> None:
        if len(packet) < BINARY_HEADER.size:
            return
        stream_id = BINARY_HEADER.unpack_from(packet)[0]
        stream = self.streams.get(stream_id)
        if stream is None:
            return
        try:
            await stream.feed(packet[BINARY_HEADER.size:])
        except Exception as exc:
            await self.complete_stream(stream, error=operation_error(exc)[1])

    async def complete_stream(
        self,
        stream: BaseStream,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        if self.streams.get(stream.stream_id) is not stream:
            return
        self.streams.pop(stream.stream_id, None)
        try:
            await stream.close(False)
        except Exception:
            pass
        message = {
            "type": "stream_closed",
            "id": stream.stream_id,
            "ok": error is None,
            "result": result or {},
        }
        if error is not None:
            message["error"] = error
        try:
            await self.send_json(message)
        except Exception:
            pass

    async def close_all_streams(self) -> None:
        streams = list(self.streams.values())
        self.streams.clear()
        for stream in streams:
            try:
                await stream.close(False)
            except Exception:
                pass

    async def heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(15)
                await self.send_json({"type": "heartbeat", "ts": int(time.time())})
        except asyncio.CancelledError:
            return

    async def session(self) -> None:
        kwargs = websocket_connect_kwargs(self.token)
        async with websockets.connect(self.url, **kwargs) as websocket:
            self.websocket = websocket
            self.send_lock = asyncio.Lock()
            await self.send_json({"type": "hello", "capabilities": self.capabilities()})
            log.info("远程访问通道已连接: %s", self.url)
            heartbeat = asyncio.ensure_future(self.heartbeat_loop())
            try:
                async for raw_message in websocket:
                    if isinstance(raw_message, bytes):
                        await self.handle_binary(raw_message)
                        continue
                    try:
                        message = json.loads(raw_message)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(message, dict):
                        continue
                    message_type = message.get("type")
                    if message_type == "request":
                        asyncio.ensure_future(self.handle_request(message))
                    elif message_type == "stream_open":
                        await self.handle_stream_open(message)
                    elif message_type == "stream_control":
                        await self.handle_stream_control(message)
                    elif message_type == "stream_close":
                        await self.handle_stream_close(message)
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                await self.close_all_streams()
                self.websocket = None

    async def run_forever(self) -> None:
        delay = 1
        while True:
            try:
                await self.session()
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("远程访问通道断开: %s；%s 秒后重连", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)


def main() -> None:
    parser = argparse.ArgumentParser(description="DevicesWebControl Remote Access Agent")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_FILE))
    parser.add_argument("--server", default="", help="仅覆盖本 Agent 使用的平台入口")
    args = parser.parse_args()
    config_path = Path(args.config).expanduser().resolve()
    configured_server, token = load_config(config_path)
    server = (
        str(args.server or "").strip().rstrip("/")
        or os.environ.get("DWC_REMOTE_SERVER", "").strip().rstrip("/")
        or configured_server
    )
    url = websocket_url(server)
    log.info(
        "启动远程访问 Agent: root=%s ssh=%s:%s vnc=%s:%s",
        REMOTE_ROOT,
        SSH_HOST,
        SSH_PORT,
        VNC_HOST,
        VNC_PORT,
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(RemoteAccessAgent(url, token).run_forever())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
