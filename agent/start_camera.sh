#!/bin/sh
exec /usr/local/bin/mjpg_streamer \
  -i "/usr/local/lib/mjpg-streamer/input_uvc.so -d /dev/video0 -r 640x480 -f 15 -y" \
  -o "/usr/local/lib/mjpg-streamer/output_http.so -p 8080 -w /usr/local/share/mjpg-streamer/www"
