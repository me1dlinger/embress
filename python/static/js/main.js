new Vue({
  delimiters: ["[[", "]]"],
  el: "#app",
  data: {
    // 认证相关
    isAuthenticated: false,
    accessKey: "",
    authLoading: false,
    authError: "",

    // 选项卡
    activeTab: "dashboard",

    // 系统状态
    systemStatus: null,
    statusLoading: false,
    lastScanResult: null,

    // 扫描相关
    scanLoading: false,

    // 历史记录
    history: [],
    historyLoading: false,

    // 变更记录
    changeRecords: [],
    recordsLoading: false,

    // 日志相关
    logFiles: [],
    selectedLogFile: null,
    logContent: "",
    logsLoading: false,
    logContentLoading: false,
    logContentError: "",

    logContentError: "",
    showSubPathModal: false,
    showSubPathRollbackModal: false,
    subPath: "",
    subScanLoading: false,
    showUnrenamedModal: false,
    unrenamedFiles: [],
    addToWhitelistLoading: false,

    showWhitelistModal: false,
    whitelistFiles: [],
    whitelistLoading: false,
    deleteFromWhitelistLoading: false,
    showRegexModal: false,
    regexPatterns: {
      season_episode: [],
      episode_only: [],
    },
    regexLoading: false,
    regexSaving: false,
    regexError: "",
    newWhitelistPath: "",
    newWhitelistType: "file",
    newWhitelistItems: [],
    submitWhitelistLoading: false,
  },

  mounted() {
    this.autoAuthenticate();
  },

  methods: {
    // 认证相关方法
    async authenticate() {
      this.authLoading = true;
      this.authError = "";

      try {
        const response = await fetch("/api/auth", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ access_key: this.accessKey }),
        });

        const result = await response.json();

        if (result.success) {
          this.isAuthenticated = true;
          localStorage.setItem("access_key", this.accessKey);
          this.loadInitialData();
        } else {
          this.authError = result.message;
          localStorage.removeItem("access_key");
        }
      } catch (error) {
        console.error("认证请求失败:", error);
        this.authError = "网络错误";
        localStorage.removeItem("access_key");
      } finally {
        this.authLoading = false;
      }
    },

    async autoAuthenticate() {
      const savedKey = localStorage.getItem("access_key");
      if (!savedKey) return;

      this.accessKey = savedKey;
      this.authLoading = true;
      this.isAuthenticated = true;
      try {
        const response = await fetch("/api/auth", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ access_key: savedKey }),
        });

        const result = await response.json();

        if (result.success) {
          this.isAuthenticated = true;
          this.loadInitialData();
        } else {
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "自动验证失败，请重新输入密钥";
        }
      } catch (error) {
        this.isAuthenticated = false;
        localStorage.removeItem("access_key");
        this.authError = "自动验证失败，请重试";
      } finally {
        this.authLoading = false;
      }
    },

    loadInitialData() {
      this.loadSystemStatus();
      this.loadHistory();
      this.loadChangeRecords();
      this.loadLogFiles();
    },

    // 系统状态相关方法
    async loadSystemStatus() {
      this.statusLoading = true;

      try {
        const response = await fetch("/api/status");
        const data = await response.json();

        this.systemStatus = data;

        if (data.last_scan) {
          this.lastScanResult = data.last_scan;
        }
      } catch (error) {
        console.error("加载系统状态失败:", error);
        this.systemStatus = null;
      } finally {
        this.statusLoading = false;
      }
    },

    // 手动扫描
    async performManualScan() {
      this.scanLoading = true;

      try {
        const response = await fetch("/api/manual-scan", {
          method: "POST",
        });

        const data = await response.json();

        if (data.success) {
          this.lastScanResult = data.result;
          // 刷新其他数据
          this.loadHistory();
          this.loadChangeRecords();
          this.loadSystemStatus();
        } else {
          alert(
            "扫描失败: " + (data.result ? data.result.message : "未知错误")
          );
        }
      } catch (error) {
        console.error("手动扫描失败:", error);
        alert("扫描失败: 网络错误");
      } finally {
        this.scanLoading = false;
      }
    },

    // 加载扫描历史
    async loadHistory() {
      this.historyLoading = true;

      try {
        const response = await fetch("/api/history");
        const data = await response.json();

        this.history = data.history || [];
      } catch (error) {
        console.error("加载历史失败:", error);
        this.history = [];
      } finally {
        this.historyLoading = false;
      }
    },

    // 加载变更记录
    async loadChangeRecords() {
      this.recordsLoading = true;

      try {
        const response = await fetch("/api/change-records");
        const data = await response.json();

        this.changeRecords = data.records || [];
      } catch (error) {
        console.error("加载变更记录失败:", error);
        this.changeRecords = [];
      } finally {
        this.recordsLoading = false;
      }
    },

    // 加载日志文件列表
    async loadLogFiles() {
      this.logsLoading = true;

      try {
        const response = await fetch("/api/logs");
        const data = await response.json();

        this.logFiles = data.logs || [];
      } catch (error) {
        console.error("加载日志文件失败:", error);
        this.logFiles = [];
      } finally {
        this.logsLoading = false;
      }
    },

    // 加载日志内容
    async loadLogContent(filename) {
      this.selectedLogFile = filename;
      this.logContentLoading = true;
      this.logContentError = "";

      try {
        const response = await fetch(`/api/logs/${filename}`);
        const data = await response.json();

        if (data.error) {
          this.logContentError = data.error;
          this.logContent = "";
        } else {
          this.logContent = data.content;
          this.logContentError = "";
        }
      } catch (error) {
        console.error("加载日志内容失败:", error);
        this.logContentError = "加载失败";
        this.logContent = "";
      } finally {
        this.logContentLoading = false;
      }
    },

    // 工具方法
    formatDate(timestamp) {
      return new Date(timestamp).toLocaleString();
    },

    closeSubPathModal() {
      this.showSubPathModal = false;
      this.subPath = ""; // 关闭时顺便清空
    },
    closeSubPathRollbackModal() {
      this.showSubPathRollbackModal = false;
      this.subPath = ""; // 关闭时顺便清空
    },
    async performSubScan() {
      if (!this.subPath.trim()) {
        alert("请输入子路径");
        return;
      }

      this.subScanLoading = true;
      try {
        const resp = await fetch("/api/scan-directory", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sub_path: this.subPath.trim() }),
        });
        const data = await resp.json();

        if (data.success) {
          this.lastScanResult = data.result;
          // 刷新相关面板
          this.loadHistory();
          this.loadChangeRecords();
          this.loadSystemStatus();
          // 自动关闭
          this.closeSubPathModal();
        } else {
          alert(
            "扫描失败: " + (data.result ? data.result.message : "未知错误")
          );
        }
      } catch (err) {
        console.error("指定路径扫描失败:", err);
        alert("扫描失败: 网络错误");
      } finally {
        this.subScanLoading = false;
      }
    },
    async performSubRollBack() {
      if (!this.subPath.trim()) {
        alert("请输入子路径");
        return;
      }

      this.subScanLoading = true;
      try {
        const resp = await fetch("/api/rollback-season", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sub_path: this.subPath.trim() }),
        });
        const data = await resp.json();
        if (data.success) {
          this.lastScanResult = data.result;
          // 刷新相关面板
          this.loadHistory();
          this.loadChangeRecords();
          this.loadSystemStatus();
          this.closeSubPathRollbackModal();
        } else {
          alert(
            "扫描失败: " + (data.result ? data.result.message : "未知错误")
          );
        }
      } catch (err) {
        console.error("指定路径回滚失败:", err);
        alert("扫描失败: 网络错误");
      } finally {
        this.subScanLoading = false;
      }
    },
    showUnrenamedFiles(files) {
      this.unrenamedFiles = files || [];
      this.showUnrenamedModal = true;
    },

    // 关闭未重命名文件弹窗
    closeUnrenamedModal() {
      this.showUnrenamedModal = false;
      this.unrenamedFiles = [];
    },
    // 显示白名单文件弹窗
    async showWhitelist() {
      try {
        const response = await fetch("/api/whitelist");
        const data = await response.json();

        this.whitelistFiles = data.whitelist || [];
        this.showWhitelistModal = true;
      } catch (error) {
        console.error("加载白名单文件失败:", error);
        this.whitelistFiles = [];
      }
    },
    async getWhitelist() {
      try {
        const response = await fetch("/api/whitelist");
        const data = await response.json();
        this.whitelistFiles = data.whitelist || [];
      } catch (error) {
        console.error("加载白名单文件失败:", error);
        this.whitelistFiles = [];
      }
    },
    // 关闭未重命名文件弹窗
    closeWhitelistModal() {
      this.showWhitelistModal = false;
      this.whitelistFiles = [];
    },
    // 添加到白名单
    async addToWhitelist(filePath) {
      this.addToWhitelistLoading = true;

      try {
        // 预留接口调用
        const response = await fetch("/api/whitelist", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            file_path: filePath,
          }),
        });

        const result = await response.json();

        if (result.success) {
          // 添加成功，从列表中移除该文件
          this.unrenamedFiles = this.unrenamedFiles.filter(
            (file) => file.path !== filePath
          );

          // 如果列表为空，关闭弹窗
          if (this.unrenamedFiles.length === 0) {
            this.closeUnrenamedModal();
          }

          // 刷新数据
          this.loadSystemStatus();
          this.loadHistory();
        } else {
          alert("添加到白名单失败: " + result.message);
        }
      } catch (error) {
        console.error("添加白名单失败:", error);
        alert("添加到白名单失败: 网络错误");
      } finally {
        this.addToWhitelistLoading = false;
      }
    },
    async deleteFromWhitelist(filePath) {
      this.deleteFromWhitelistLoading = true;

      try {
        const response = await fetch("/api/whitelist", {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            file_path: filePath,
          }),
        });

        const result = await response.json();

        if (result.success) {
          this.whitelistFiles = this.whitelistFiles.filter(
            (file) => file.path !== filePath
          );

          // 如果列表为空，关闭弹窗
          if (this.whitelistFiles.length === 0) {
            this.closeWhitelistModal();
          }
          // 刷新数据
          this.loadSystemStatus();
          this.loadHistory();
        } else {
          alert("移出白名单失败: " + result.message);
        }
      } catch (error) {
        console.error("移出白名单失败:", error);
        alert("移出白名单失败: 网络错误");
      } finally {
        this.deleteFromWhitelistLoading = false;
      }
    },
    addNewWhitelist() {
      const path = this.newWhitelistPath.trim();
      if (!path) return;
      const exists =
        this.whitelistFiles.includes(path) ||
        this.newWhitelistItems.some((item) => item.path === path);

      if (exists) {
        alert("该路径已在白名单中");
        return;
      }
      this.newWhitelistItems.push({
        path: path,
        type: this.newWhitelistType,
      });
      this.newWhitelistPath = "";
      this.newWhitelistType = "file";
    },

    // 移除新增的白名单项
    removeNewWhitelistItem(index) {
      this.newWhitelistItems.splice(index, 1);
    },
    getNewWhitelistItems() {
      return this.newWhitelistItems.map((item) => ({
        path: item.path,
        type: item.type,
        timestamp: new Date().toISOString(),
      }));
    },

    async submitNewWhitelistItems() {
      if (this.newWhitelistItems.length === 0) return;
      this.addToWhitelistLoading = true;
      try {
        const response = await fetch("/api/whitelist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: this.getNewWhitelistItems() }),
        });
        const result = await response.json();

        if (result.success) {
          this.newWhitelistItems = [];
          this.loadSystemStatus();
          this.loadHistory();
          this.whi;
        } else {
          alert("批量加入白名单失败: " + result.message);
        }
      } catch (err) {
        console.error("批量加入白名单失败:", err);
        alert("网络错误");
      } finally {
        this.addToWhitelistLoading = false;
        this.getWhitelist();
      }
    },
    closeWhitelistModal() {
      this.showWhitelistModal = false;
      this.newWhitelistItems = [];
      this.newWhitelistPath = "";
      this.newWhitelistType = "file";
    },

    getFileName(filePath) {
      const normalized = filePath.replace(/[\\/]+/g, "/").replace(/\/$/, "");
      return normalized.substring(normalized.lastIndexOf("/") + 1);
    },

    getDirectoryPath(filePath) {
      const normalized = filePath.replace(/[\\/]+/g, "/").replace(/\/$/, "");
      const lastIndex = normalized.lastIndexOf("/");
      if (lastIndex === -1) return "";
      const directoryPath = normalized.substring(0, lastIndex);
      if (/^[a-zA-Z]:$/.test(directoryPath)) {
        return directoryPath + "/";
      }

      return directoryPath || "/";
    },
    async showRegexConfig() {
      this.showRegexModal = true;
      this.regexError = "";
      await this.loadRegexPatterns();
    },

    // 关闭正则表达式配置弹窗
    closeRegexModal() {
      this.showRegexModal = false;
      this.regexError = "";
    },

    // 加载正则表达式配置
    async loadRegexPatterns() {
      this.regexLoading = true;

      try {
        const response = await fetch("/api/regex-patterns");
        const data = await response.json();

        if (data.success) {
          // 确保格式化为数组
          if (typeof data.patterns === "string") {
            this.regexPatterns = JSON.parse(data.patterns);
          } else {
            this.regexPatterns = data.patterns;
          }
        } else {
          this.regexError = "加载失败: " + data.message;
        }
      } catch (error) {
        console.error("加载正则配置失败:", error);
        this.regexError = "加载失败: 网络错误";
      } finally {
        this.regexLoading = false;
      }
    },
    addRegexItem(type) {
      this.regexPatterns[type].push("");
    },
    removeRegexItem(type, index) {
      this.regexPatterns[type].splice(index, 1);
    },
    // 保存正则表达式配置
    async saveRegexPatterns() {
      this.regexSaving = true;
      this.regexError = "";

      try {
        const response = await fetch("/api/regex-patterns", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(this.regexPatterns),
        });

        const result = await response.json();

        if (result.success) {
          // 保存成功，关闭弹窗
          this.closeRegexModal();
          // 可选：显示成功提示
          alert("正则配置已保存");
        } else {
          this.regexError = "保存失败: " + result.message;
        }
      } catch (error) {
        console.error("保存正则配置失败:", error);
        this.regexError = "保存失败: 网络错误";
      } finally {
        this.regexSaving = false;
      }
    },
  },
});
