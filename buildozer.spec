[app]

title = taoSync
package.name = taosync
package.domain = org.taofang

source.dir = .
source.include_exts = py,png,jpg,jpeg,html,js,css,ttf,otf,svg,ico,json,gif,woff,woff2,map
source.include_patterns = front/**,common/**,controller/**,mapper/**,service/**,doc/config.ini

version = 0.3.2

requirements = python3,pyjnius,android,tornado,requests,urllib3,certifi,chardet,idna,apscheduler,tzlocal,tzdata,setuptools,configparser,pathspec,openssl,sqlite3

orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,WAKE_LOCK,FOREGROUND_SERVICE,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,POST_NOTIFICATIONS

android.api = 33
android.minapi = 21
android.ndk_api = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

android.wakelock = True
android.allow_backup = True
android.apptheme = @android:style/Theme.NoTitleBar
android.presplash_color = #FFFFFF
android.showlog = 0
# buildozer 标准配置项为 icon.filename（android.icon 非标准，会被忽略）
# 要求 512x512 PNG，会自动生成各分辨率 mipmap
icon.filename = %(source.dir)s/logo.png

p4a.branch = v2024.01.21
p4a.bootstrap = webview
# WebView 启动后自动跳转到 /__logview__ 显示日志，/ 是业务前端
p4a.extra_args = --port=8023

android.release_artifact = apk
android.debug_artifact = apk

log_level = 2

[buildozer]

log_level = 2
warn_on_root = 1

bin_dir = bin
