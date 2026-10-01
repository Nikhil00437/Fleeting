const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("fleetingDesktop", {
  isElectron: true,
  platform: process.platform,
  minimize: () => ipcRenderer.invoke("window:minimize"),
  toggleMaximize: () => ipcRenderer.invoke("window:toggle-maximize"),
  close: () => ipcRenderer.invoke("window:close"),
  isMaximized: () => ipcRenderer.invoke("window:is-maximized"),
  openExternal: (url) => ipcRenderer.invoke("shell:open-external", url),
  onMaximizeChange: (cb) => {
    const handler = (_event, maximized) => cb(Boolean(maximized));
    ipcRenderer.on("window:maximized", handler);
    return () => ipcRenderer.removeListener("window:maximized", handler);
  },
  onNavigate: (cb) => {
    const handler = (_event, target) => cb(target);
    ipcRenderer.on("app:navigate", handler);
    return () => ipcRenderer.removeListener("app:navigate", handler);
  },
});
