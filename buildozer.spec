[app]
title = HealthMonitor
package.name = health
package.domain = org.test
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
# 必须包含这些库才能使用地图和蓝牙
requirements = python3,kivy,mapview,jnius
# 必须申请这些安卓权限
android.permissions = BLUETOOTH, BLUETOOTH_ADMIN, BLUETOOTH_CONNECT, BLUETOOTH_SCAN, INTERNET, ACCESS_FINE_LOCATION
android.archs = arm64-v8a
orientation = portrait
fullscreen = 0

[buildozer]
log_level = 2
warn_on_root = 1
