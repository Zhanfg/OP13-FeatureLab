# Gallery Visibility Engine (experimental)

基于 `Vstory/ColorOSGalleryNomediaGuard` 的实验分支实现，保留原有 ColorOS 相册 `.nomedia` 防护，并加入：

- 默认隔离第三方媒体目录；
- 相机 / 截图 / ColorOS 常用输出目录默认可见；
- 模块设置页可通过系统目录选择器添加“透传目录”；
- 透传目录优先级高于默认隔离和 `.nomedia`，用于显式允许第三方 App 媒体进入相册；
- libxposed RemotePreferences 跨进程同步，Hook 侧热更新策略；
- 目录级内存缓存，避免每一行查询都重复向上 stat 整条路径；
- 策略变化后后台重建隐藏 ID 索引、清理 ColorOS local_media 隐藏行并驱动 Gallery 原生同步；
- 加入初步增量 MediaScanner，用于帮助已透传目录进入 MediaStore。

## 当前边界

本 alpha **尚未直接扩大静态作用域到 Android 16 系统 Photo Picker / MediaProvider**。先保证 ColorOS Gallery 本体稳定；仓库同时提供 `tools/PickerProbe.sh`，用于实机确定 OnePlus 13 当前系统媒体选择器的真实包名/进程和 provider，再接入 Picker Adapter，避免猜包名后把系统媒体链路整体 Hook 坏。

版本：`1.4.0-alpha1`

## 构建

```bash
gradle :app:assembleDebug
```

CI workflow 会生成 debug APK artifact。

## 上游与许可证

核心 `.nomedia` Hook / GalleryProvider 过滤逻辑派生自：

- https://github.com/Vstory/ColorOSGalleryNomediaGuard

上游为 GPL-3.0，本实验子工程同样按 GPL-3.0 处理。详见 `THIRD_PARTY_NOTICES.md`。
