# 项目运行规则

## Python / Conda 环境

- 本项目后端必须使用 Conda 环境 `DevicesWebControl`。
- Python 可执行文件固定为：`D:/ProgramData/miniforge3/envs/DevicesWebControl/python.exe`。
- 安装 Python 依赖时，不要直接调用系统的 `pip` 或其他 Python 环境。应使用：

  ```powershell
  D:/ProgramData/miniforge3/envs/DevicesWebControl/python.exe -m pip install <package>
  ```

- 执行后端 Python 脚本、模块、测试或管理命令时，也应使用上述 Python 可执行文件。

## 启动后端

在 `backend` 目录中运行：

```powershell
D:/ProgramData/miniforge3/envs/DevicesWebControl/python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 1
```

## 启动前端

在 `frontend` 目录中运行：

```powershell
npm run dev
```

## 代码完成后的验证

- 完成代码编写后，默认不自动执行构建、测试或 ESLint。
- 默认不打开浏览器，也不进行截图验证。
- 代码运行效果和功能正确性由用户自行验证，除非用户明确要求执行上述验证操作。
