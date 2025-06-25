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
    subPath: "",
    subScanLoading: false,
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
  },
});
