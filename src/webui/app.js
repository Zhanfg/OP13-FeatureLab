// SPDX-License-Identifier: GPL-3.0-only
import { MODULE_ID, STATUS_BRIDGE } from "./runtime-config.js";

const $ = (id) => document.getElementById(id);
const fatal = $("fatal");
const content = $("content");

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

function showFatal(message) {
  $("fatal-detail").textContent = message;
  fatal.classList.remove("hidden");
  content.classList.add("hidden");
}

function setText(id, value) {
  $(id).textContent = String(value ?? "—");
}

function validateStatus(value) {
  if (!value || value.schema !== 1 || value.ok !== true || value.read_only !== true) throw new Error("状态桥返回格式无效");
  if (value.capabilities?.mutation_enabled !== false) throw new Error("状态桥未处于只读模式");
  return value;
}

function hslFromHex(hex) {
  const value = hex.replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(value)) return { h: 260, s: 36, l: 48 };
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  const l = (max + min) / 2;
  const s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
  return { h: Math.round(h), s: Math.round(s * 100), l: Math.round(l * 100) };
}

function applySeed(seed) {
  const { h, s } = hslFromHex(seed);
  const dark = document.documentElement.dataset.theme === "dark";
  document.documentElement.style.setProperty("--seed", seed);
  document.documentElement.style.setProperty("--primary", `hsl(${h} ${Math.max(36, s)}% ${dark ? 76 : 42}%)`);
  document.documentElement.style.setProperty("--primary-container", `hsl(${h} ${Math.max(32, s)}% ${dark ? 28 : 90}%)`);
  document.documentElement.style.setProperty("--on-primary-container", `hsl(${h} 42% ${dark ? 92 : 18}%)`);
  document.documentElement.style.setProperty("--secondary-container", `hsl(${(h + 28) % 360} 28% ${dark ? 28 : 91}%)`);
}

function addSafetyItem(label, good, detail) {
  const li = document.createElement("li");
  const name = document.createElement("span");
  const state = document.createElement("strong");
  name.textContent = label;
  state.textContent = detail;
  state.className = good ? "status-ok" : "status-warn";
  li.append(name, state);
  $("safety-list").append(li);
}

function render(status) {
  applySeed(status.theme.seed);
  setText("theme-source", `取色 ${status.theme.source}`);
  setText("module-line", `${status.module.id} · ${status.module.version} (${status.module.version_code})`);
  setText("runtime-status", status.runtime.status);
  setText("runtime-detail", `${status.runtime.active_mounts} 个挚载 · namespace ${status.runtime.namespace}`);
  setText("property-status", status.properties.status);
  setText("property-detail", `${status.properties.active_properties} 个属性 · ${status.properties.reboot_required ? "需重启" : "无需重启标记"}`);
  setText("integrity-status", status.integrity.status);
  setText("integrity-detail", status.integrity.status === "pass" ? "不可变文件校验通过" : "未通过完整校验");
  setText("boot-status", status.boot.completed ? "completed" : "incomplete");
  setText("boot-detail", `失败计数 ${status.boot.failure_count}`);
  setText("device-product", status.device.product);
  setText("device-model", status.device.model);
  setText("device-sdk", status.device.sdk);
  setText("device-rom", status.device.oplus_rom);
  setText("device-selinux", status.boot.selinux);

  $("safety-list").replaceChildren();
  addSafetyItem("只读状态桥", status.capabilities.status_bridge && !status.capabilities.mutation_enabled, "启用");
  addSafetyItem("运行时恢复", !status.runtime.recovery, status.runtime.recovery ? "已触发" : "未触发");
  addSafetyItem("属性恢复", !status.properties.recovery, status.properties.recovery ? "已触发" : "未触发");
  addSafetyItem("载荷完整性", status.integrity.status === "pass", status.integrity.status);

  setText("error-count", status.errors.length);
  const errors = $("errors");
  errors.replaceChildren();
  if (!status.errors.length) {
    errors.className = "empty-state";
    errors.textContent = "未检测到状态桥错误。";
  } else {
    const list = document.createElement("ul");
    list.className = "error-list";
    status.errors.forEach((code) => {
      const item = document.createElement("li");
      item.textContent = code;
      list.append(item);
    });
    errors.className = "";
    errors.append(list);
  }
  fatal.classList.add("hidden");
  content.classList.remove("hidden");
}

async function locateModule(exec) {
  if (!/^[A-Za-z0-9._-]+$/.test(MODULE_ID)) throw new Error("模块 ID 配置无效");
  const expected = shellQuote(MODULE_ID);
  const command = `for d in /data/adb/modules/*; do [ -f "$d/module.prop" ] || continue; mid="$(sed -n 's/^id=//p' "$d/module.prop" | head -n 1)"; [ "$mid" = ${expected} ] || continue; printf '%s\\n' "$d"; exit 0; done; exit 44`;
  const result = await exec(command);
  if (Number(result.errno) !== 0) throw new Error(`未找到已安装模块（errno ${result.errno}）`);
  const path = String(result.stdout ?? "").trim();
  if (!/^\/data\/adb\/modules\/[A-Za-z0-9._-]+$/.test(path)) throw new Error("模块路径验证失败");
  return path;
}

async function loadStatus() {
  $("refresh").disabled = true;
  try {
    const api = await import("kernelsu");
    if (typeof api.exec !== "function") throw new Error("KernelSU exec API 不可用");
    const modulePath = await locateModule(api.exec);
    if (!/^[A-Za-z0-9_./-]+$/.test(STATUS_BRIDGE)) throw new Error("状态桥配置无效");
    const result = await api.exec(`sh ${shellQuote(`${modulePath}/${STATUS_BRIDGE}`)} status`);
    if (Number(result.errno) !== 0) throw new Error(`状态桥执行失败（errno ${result.errno}）`);
    let parsed;
    try { parsed = JSON.parse(String(result.stdout ?? "")); }
    catch { throw new Error("状态桥未返回有效 JSON"); }
    render(validateStatus(parsed));
  } catch (error) {
    showFatal(error instanceof Error ? error.message : "未知 API 错误");
  } finally {
    $("refresh").disabled = false;
  }
}

function initializeTheme() {
  const stored = localStorage.getItem("featurelab-theme");
  const dark = stored ? stored === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

$("theme-toggle").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("featurelab-theme", next);
  loadStatus();
});
$("refresh").addEventListener("click", loadStatus);
initializeTheme();
loadStatus();
