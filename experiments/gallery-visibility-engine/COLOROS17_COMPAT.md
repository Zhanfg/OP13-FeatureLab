# ColorOS 17 compatibility mapping

Probe source: OnePlus PJZ110, Android/ColorOS 17, Gallery 17.10.6.

## Verified package/runtime changes

- Gallery package remains `com.coloros.gallery3d`.
- Gallery version: `17.10.6` (system fallback `17.9.24`).
- MediaProvider: `com.android.providers.media.module`, Android 17.
- Standalone Android 17 Photo Picker exists as `com.android.photopicker`, version `17.0.14`.

## Verified ColorOS 17 internal mapping

ColorOS 16 chain used by the old module:

- `MediaDBSyncDM.j()`
- `gyq.run()`
- `iyq.a(String,String,HashMap,HashMap): boolean`
- `loo` as MediaSyncManager

ColorOS 17.10.6 probe shows:

- `MediaDBSyncDM.i()` contains the `startNomediaCheckTask` path.
- `uks.run()` is the NomediaScanner task.
- `wks.a(String,String,HashMap,HashMap): boolean` is the nomedia decision function called by `uks.run()`.
- `fgq` is the MediaSyncManager replacement and keeps the same structural contract:
  - `fgq.f() -> fgq singleton`
  - `fgq.a(fgq, boolean, Uri) -> void` from the ContentObserver onChange path.
- `GalleryProvider` remains `com.oplus.gallery.foundation.database.provider.GalleryProvider`, but the query overload family changed from three overloads to two in 17.10.6.
- The Gallery provider authority and `local_media` / `local_media_internal` URIs remain present.

## Implementation strategy

The module now resolves the semantic roles by candidate/structural signatures instead of a single obfuscated symbol:

- ColorOS 17 candidates first, ColorOS 16 fallbacks second.
- GalleryProvider query overloads are discovered reflectively by method shape.
- `local_media` additionally has ContentResolver URI-level filtering, so a future provider class rename is fail-open instead of fatal.
- MediaSyncManager tries `fgq` then `loo`.
- Android 17 standalone `com.android.photopicker` is included in static scope.
