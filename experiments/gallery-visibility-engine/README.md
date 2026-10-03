# Gallery Visibility Engine (experimental)

当前版本：`1.5.0-alpha1`

基于 `Vstory/ColorOSGalleryNomediaGuard` 的实验实现，现已扩展为：

- 默认隔离第三方媒体；
- Camera / Screenshots / ColorOS 常用目录默认可见；
- **应用透传**：直接选择应用，不再要求用户自己寻找媒体目录；
- **默认通讯透传**：微信、QQ、Telegram、WhatsApp、企业微信、Signal、LINE、Discord、钉钉、飞书等常见通讯软件首装默认开启；
- 应用透传同时使用三层识别：
  1. `Android/media/<package>` 通用目录；
  2. 微信/QQ/Telegram/WhatsApp 等兼容历史目录；
  3. MediaStore `owner_package_name` 精确归属索引；
- **文件夹透传仍保留**，用于历史目录、特殊应用和自定义媒体树；
- 配置通过 libxposed RemotePreferences 热更新到目标进程；
- 继续保留上游 `.nomedia` 保护、GalleryProvider 过滤与 local_media 实时刷新。

## Android Photo Picker acceleration

`1.5.0-alpha1` 开始把 Android 16 Photo Picker 加入独立加速通道。加速器只在
`:PhotoPicker` UI 进程运行，不进入 MediaProvider 数据库主进程。

当前优化包括：

- 小分页请求适度提升到 64–96 项；
- 短时 LRU Cursor 快照缓存；
- 基于返回的 next-page key 自动预取下一页；
- 仅对本地媒体做缩略图预热，不主动拉取云媒体；
- 合并极短时间内重复的 `picker_media_init` / `ensure_providers_call`；
- 缓存严格限量并带 TTL，避免大图库内存膨胀。

支持作用域：

- `com.coloros.gallery3d`
- `com.android.providers.media.module`
- `com.google.android.providers.media.module`
- `com.google.android.photopicker`

Android 16 的标准 Photo Picker 由 MediaProvider 模块承载，Picker Activity 位于独立
`:PhotoPicker` 进程；本实现按这个进程边界分流，不把 ColorOS Gallery 专用 Hook
装入系统 MediaProvider 数据进程。

## 构建

```bash
gradle :app:assembleDebug
```

GitHub Actions 会上传：

`GalleryVisibilityEngine-1.5.0-alpha1`

## 上游与许可证

核心 ColorOS `.nomedia` / GalleryProvider 逻辑派生自：

- https://github.com/Vstory/ColorOSGalleryNomediaGuard

上游为 GPL-3.0，本实验子工程继续按 GPL-3.0 处理。
