# KernelSU WebUI direct bridge note

KernelSU Manager injects a JavaScript interface named `ksu` into the module WebView. Raw browser modules cannot resolve the bare npm specifier `kernelsu` unless the WebUI is bundled first. FeatureLab therefore uses the injected `window.ksu` bridge directly in its unbundled WebUI and keeps mutation disabled in the validation control plane.
