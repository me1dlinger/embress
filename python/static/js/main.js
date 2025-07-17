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

    showScanIntervalModal: false,
    scanInterval: 600,
    scanIntervalLoading: false,
    scanIntervalError: "",
    // 扫描相关
    scanLoading: false,

    // 历史记录
    history: [],
    historyLoading: false,

    // 变更记录
    showsChangeList: [],
    selectedShow: {
      media_type: null,
      show_name: null,
    },
    selectedShowRecords: [],
    selectedTypeFilter: "all",
    recordsLoading: false,
    groupBy: "type",
    typeOrder: [
      "rename",
      "subtitle_rename",
      "audio_rename",
      "picture_rename",
      "nfo_delete",
    ],
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

    renameLoading: false,

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

    showModal: false,
    modalType: "info",
    modalTitle: "提示",
    modalContent: "这是一条消息",
    modalIcon: "bi-info-circle",
    hasCancel: false,
    confirmCallback: null,
    toasts: [],
    toastId: 0,

    showFilteredOnly: false,
  },

  mounted() {
    this.autoAuthenticate();
  },
  computed: {
    // 按类型统计记录数量
    recordTypeStats() {
      const stats = {};
      this.selectedShowRecords.forEach((record) => {
        stats[record.type] = (stats[record.type] || 0) + 1;
      });
      const orderedStats = {};
      this.typeOrder.forEach((type) => {
        if (stats[type]) {
          orderedStats[type] = stats[type];
        }
      });
      return orderedStats;
    },
    seasonStats() {
      const stats = {};
      this.selectedShowRecords.forEach((record) => {
        const seasonName = record.season_name || "未知季度";
        stats[seasonName] = (stats[seasonName] || 0) + 1;
      });
      const sortedStats = {};
      Object.keys(stats)
        .sort((a, b) => {
          // 自定义排序逻辑
          return this.compareSeasonNames(a, b);
        })
        .forEach((season) => {
          sortedStats[season] = stats[season];
        });

      return sortedStats;
    },
    // 按类型分组的记录
    groupedRecordsByType() {
      const groups = {};
      this.selectedShowRecords.forEach((record) => {
        if (!groups[record.type]) {
          groups[record.type] = [];
        }
        groups[record.type].push(record);
      });

      // 按时间排序每个分组
      Object.keys(groups).forEach((type) => {
        groups[type].sort(
          (a, b) => new Date(b.timestamp) - new Date(a.timestamp)
        );
      });

      const orderedGroups = {};
      this.typeOrder.forEach((type) => {
        if (groups[type]) {
          orderedGroups[type] = groups[type];
        }
      });

      return orderedGroups;
    },
    groupedRecordsBySeason() {
      const groups = {};
      this.selectedShowRecords.forEach((record) => {
        const seasonName = record.season_name || "未知季度";
        if (!groups[seasonName]) {
          groups[seasonName] = [];
        }
        groups[seasonName].push(record);
      });

      // 按时间排序每个分组
      Object.keys(groups).forEach((season) => {
        groups[season].sort(
          (a, b) => new Date(b.timestamp) - new Date(a.timestamp)
        );
      });
      const sortedGroups = {};
      Object.keys(groups)
        .sort((a, b) => {
          return this.compareSeasonNames(a, b);
        })
        .forEach((season) => {
          sortedGroups[season] = groups[season];
        });

      return sortedGroups;
    },
    groupedRecords() {
      if (this.groupBy === "season") {
        return this.groupedRecordsBySeason;
      } else {
        return this.groupedRecordsByType;
      }
    },
    // 筛选后的记录
    filteredRecords() {
      if (this.selectedTypeFilter === "all") {
        return this.selectedShowRecords;
      }
      if (this.groupBy === "season") {
        return this.selectedShowRecords.filter(
          (record) => record.season_name === this.selectedTypeFilter
        );
      } else {
        return this.selectedShowRecords.filter(
          (record) => record.type === this.selectedTypeFilter
        );
      }
    },
  },
  methods: {
    showToast(
      message,
      type = "info",
      title = null,
      duration = 3000,
      callback = null
    ) {
      const id = ++this.toastId;
      const toast = {
        id,
        message,
        type,
        title,
        duration,
        callback,
        visible: false,
      };

      this.toasts.push(toast);

      setTimeout(() => {
        const toastIndex = this.toasts.findIndex((t) => t.id === id);
        if (toastIndex !== -1) {
          this.toasts[toastIndex].visible = true;
        }
      }, 50);

      setTimeout(() => {
        this.removeToast(id);
      }, duration);

      return id;
    },
    removeToast(id) {
      const toastIndex = this.toasts.findIndex((t) => t.id === id);
      if (toastIndex !== -1) {
        const toast = this.toasts[toastIndex];

        // 执行回调
        if (toast.callback && typeof toast.callback === "function") {
          toast.callback();
        }

        this.toasts[toastIndex].visible = false;
        setTimeout(() => {
          const index = this.toasts.findIndex((t) => t.id === id);
          if (index !== -1) {
            this.toasts.splice(index, 1);
          }
        }, 300);
      }
    },
    getToastIcon(type) {
      const icons = {
        success: "bi-check-circle-fill",
        error: "bi-x-circle-fill",
        warning: "bi-exclamation-triangle-fill",
        info: "bi-info-circle-fill",
      };
      return icons[type] || icons.info;
    },
    showSuccess(message, title = null, duration = 2000, callback = null) {
      return this.showToast(message, "success", title, duration, callback);
    },

    showError(message, title = null, duration = 5000, callback = null) {
      return this.showToast(message, "error", title, duration, callback);
    },

    showWarning(message, title = null, duration = 4000, callback = null) {
      return this.showToast(message, "warning", title, duration, callback);
    },

    showInfo(message, title = null, duration = 3000, callback = null) {
      return this.showToast(message, "info", title, duration, callback);
    },
    clearAllToasts() {
      this.toasts.forEach((toast) => {
        toast.visible = false;
      });

      setTimeout(() => {
        this.toasts = [];
      }, 300);
    },
    async auth_fetch(url, options = {}) {
      const accessKey = localStorage.getItem("access_key");
      const defaultHeaders = {
        "Content-Type": "application/json",
        "X-Access-Key": accessKey || "",
      };
      const finalOptions = {
        method: "GET",
        ...options,
        headers: {
          ...defaultHeaders,
          ...(options.headers || {}),
        },
      };
      try {
        const response = await fetch(url, finalOptions);
        if (!response.ok) {
          const errorText = await response.text();
          const error = new Error(errorText || `HTTP ${response.status}`);
          error.status = response.status; // <== 关键
          throw error;
        }
        return await response.json();
      } catch (err) {
        throw err;
      }
    },
    // 认证相关方法
    async authenticate() {
      this.authLoading = true;
      this.authError = "";

      try {
        const result = await this.auth_fetch("/api/auth", {
          method: "POST",
          body: JSON.stringify({ access_key: this.accessKey }),
        });

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
        const data = await this.auth_fetch("/api/status");
        this.systemStatus = data;
        this.scanInterval = data.scan_interval;
        if (data.last_scan) {
          this.lastScanResult = data.last_scan;
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
        this.systemStatus = null;
      } finally {
        this.statusLoading = false;
      }
    },
    openScanIntervalModal() {
      this.scanInterval = this.systemStatus.scan_interval;
      this.showScanIntervalModal = true;
    },
    formatInterval(seconds) {
      if (!seconds) return "";
      if (seconds < 60) return `${seconds}秒`;
      if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`;
      if (seconds < 86400) return `${Math.floor(seconds / 3600)}小时`;
      return `${Math.floor(seconds / 86400)}天`;
    },
    async updateScanInterval() {
      if (
        !this.scanInterval ||
        this.scanInterval < 60 ||
        this.scanInterval > 86400
      ) {
        this.scanIntervalError = "请输入60-86400秒之间的值";
        return;
      }

      this.scanIntervalLoading = true;
      this.scanIntervalError = "";

      try {
        const result = await this.auth_fetch("/api/config/scan-interval", {
          method: "POST",
          body: JSON.stringify({ scan_interval: this.scanInterval }),
        });
        if (result.success) {
          this.showSuccess("扫描间隔已更新", "配置成功");
          this.loadSystemStatus();
          this.showScanIntervalModal = false;
        } else {
          this.showModalComponent(
            "error",
            "配置失败",
            data.message ? data.message : "未知错误",
            "bi-x-circle"
          );
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
      } finally {
        this.scanIntervalLoading = false;
      }
    },
    async toogleSchedulerState() {
      try {
        const data = await this.auth_fetch("/api/scheduler/toggle", {
          method: "POST",
        });
        this.loadSystemStatus();
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
      }
    },
    // 手动扫描
    async performManualScan() {
      this.scanLoading = true;

      try {
        const data = await this.auth_fetch("/api/manual-scan", {
          method: "POST",
        });

        if (data.success) {
          this.lastScanResult = data.result;
          // 刷新其他数据
          this.loadHistory();
          this.loadChangeRecords();
          this.loadSystemStatus();
          this.showSuccess("文件扫描已完成，结果已更新。", "扫描成功");
        } else {
          this.showModalComponent(
            "error",
            "扫描失败",
            data.message ? data.message : "未知错误",
            "bi-x-circle"
          );
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
      } finally {
        this.scanLoading = false;
      }
    },

    // 加载扫描历史
    async loadHistory() {
      this.historyLoading = true;
      const filterHistoryFlag = this.showFilteredOnly ? 1 : 0;
      try {
        const data = await this.auth_fetch("/api/history/" + filterHistoryFlag);

        this.history = data.history || [];
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
        this.history = [];
      } finally {
        this.historyLoading = false;
      }
    },
    setGroupBy(groupBy) {
      this.groupBy = groupBy;
      // 切换分组方式时重置筛选
      this.selectedTypeFilter = "all";
    },
    compareSeasonNames(a, b) {
      if (a === "未知季度" && b !== "未知季度") return 1;
      if (b === "未知季度" && a !== "未知季度") return -1;
      if (a === "未知季度" && b === "未知季度") return 0;

      const extractNumber = (str) => {
        const match = str.match(/第?(\d+)[季部]/);
        if (match) {
          return parseInt(match[1]);
        }
        const seasonMatch = str.match(/[Ss]eason\s*(\d+)|[Ss](\d+)/);
        if (seasonMatch) {
          return parseInt(seasonMatch[1] || seasonMatch[2]);
        }
        return str;
      };

      const numA = extractNumber(a);
      const numB = extractNumber(b);
      if (typeof numA === "number" && typeof numB === "number") {
        return numA - numB;
      }
      if (typeof numA === "number" && typeof numB === "string") {
        return -1;
      }
      if (typeof numA === "string" && typeof numB === "number") {
        return 1;
      }
      return a.localeCompare(b);
    },

    getSeasonIcon(seasonName) {
      if (seasonName.includes("第") && seasonName.includes("季")) {
        return "bi-collection text-primary";
      }
      return "bi-folder text-info";
    },
    async loadChangeRecords() {
      this.recordsLoading = true;

      try {
        if (this.selectedShow.show_name) {
          // 加载特定节目的记录
          await this.loadShowRecords();
        } else {
          // 加载节目列表
          const data = await this.auth_fetch("/api/change-records");
          this.showsChangeList = data.shows || [];
          this.showsChangeList.forEach((show) => {
            if (show.types) {
              show.types = show.types.sort((a, b) => {
                const indexA = this.typeOrder.indexOf(a);
                const indexB = this.typeOrder.indexOf(b);
                return indexA - indexB;
              });
            }
          });
        }
      } catch (error) {
        if (error.status === 401) {
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
        this.showsChangeList = [];
        this.selectedShowRecords = [];
      } finally {
        this.recordsLoading = false;
      }
    },

    async selectShow(mediaType, showName) {
      this.selectedShow = {
        media_type: mediaType,
        show_name: showName,
      };
      await this.loadShowRecords();
    },
    async loadShowRecords() {
      this.recordsLoading = true;

      try {
        const data = await this.auth_fetch("/api/change-records/show", {
          method: "POST",
          body: JSON.stringify(this.selectedShow),
        });

        this.selectedShowRecords = data.records || [];
      } catch (error) {
        this.showModalComponent(
          "error",
          "加载失败",
          "加载节目记录失败",
          "bi-x-circle"
        );
        this.selectedShowRecords = [];
      } finally {
        this.recordsLoading = false;
      }
    },

    setTypeFilter(type) {
      this.selectedTypeFilter = type;
    },
    // 返回节目列表
    goBackToShows() {
      this.selectedShow = {
        media_type: null,
        show_name: null,
      };
      this.selectedShowRecords = [];
      this.selectedTypeFilter = "all";
      this.groupBy = "type";
      this.loadChangeRecords();
    },
    getTypeIcon(type) {
      const iconMap = {
        rename: "bi-file-earmark-text text-primary",
        subtitle_rename: "bi-card-text text-info",
        audio_rename: "bi-volume-up text-success",
        picture_rename: "bi-image text-warning",
        nfo_delete: "bi-trash text-danger",
      };
      return iconMap[type] || "bi-file-earmark";
    },
    getTypeLabel(type) {
      const typeMap = {
        rename: "文件重命名",
        subtitle_rename: "字幕重命名",
        audio_rename: "音频重命名",
        picture_rename: "图片重命名",
        nfo_delete: "NFO删除",
      };
      return typeMap[type] || type;
    },

    // 格式化日期
    formatDate(timestamp) {
      if (!timestamp) return "";
      const date = new Date(timestamp);
      return date.toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    },
    async loadLogFiles() {
      this.logsLoading = true;

      try {
        const data = await this.auth_fetch("/api/logs");
        this.logFiles = data.logs || [];
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
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
        const data = await this.auth_fetch("/api/logs/" + filename);
        if (data.error) {
          this.logContentError = data.error;
          this.logContent = "";
        } else {
          this.logContent = data.content;
          this.logContentError = "";
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
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
        this.showModalComponent(
          "warning",
          "警告",
          "请输入子路径",
          "bi-exclamation-triangle"
        );
        return;
      }

      this.subScanLoading = true;
      try {
        const data = await this.auth_fetch("/api/scan-directory", {
          method: "POST",
          body: JSON.stringify({ sub_path: this.subPath.trim() }),
        });
        if (data.success) {
          this.lastScanResult = data.result;
          // 刷新相关面板
          this.loadHistory();
          this.loadChangeRecords();
          this.loadSystemStatus();
          // 自动关闭
          this.closeSubPathModal();
          this.showSuccess("指定路径的扫描操作已完成。", "扫描成功");
        } else {
          this.showModalComponent(
            "error",
            "扫描失败",
            data.message ? data.message : "未知错误",
            "bi-x-circle"
          );
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "扫描失败",
            "网络错误",
            "bi-x-circle"
          );
        }
      } finally {
        this.subScanLoading = false;
      }
    },
    async performSubRollBack() {
      if (!this.subPath.trim()) {
        this.showModalComponent(
          "warning",
          "警告",
          "请输入Season路径",
          "bi-exclamation-triangle"
        );
        return;
      }

      this.subScanLoading = true;
      try {
        const data = await this.auth_fetch("/api/rollback-season", {
          method: "POST",
          body: JSON.stringify({ sub_path: this.subPath.trim() }),
        });
        if (data.success) {
          this.lastScanResult = data.result;
          // 刷新相关面板
          this.loadHistory();
          this.loadChangeRecords();
          this.loadSystemStatus();
          this.closeSubPathRollbackModal();
          this.showSuccess("指定路径的回滚操作已完成。", "回滚成功");
        } else {
          this.showModalComponent(
            "error",
            "回滚失败",
            data.message ? data.message : "未知错误",
            "bi-x-circle"
          );
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
      } finally {
        this.subScanLoading = false;
      }
    },
    showUnrenamedFiles(files) {
      this.unrenamedFiles = files || [];
      console.log(
        "🚀 ~ showUnrenamedFiles ~ this.unrenamedFiles:",
        this.unrenamedFiles
      );

      this.showUnrenamedModal = true;
    },

    // 关闭未重命名文件弹窗
    closeUnrenamedModal() {
      const editingFile = this.unrenamedFiles.find((file) => file.isRenaming);
      if (editingFile) {
        // 取消所有正在编辑的项目
        this.unrenamedFiles.forEach((file, index) => {
          if (file.isRenaming) {
            this.cancelRename(file, index);
          }
        });
      }
      this.showUnrenamedModal = false;
    },
    // 显示白名单文件弹窗
    async showWhitelist() {
      try {
        const data = await this.auth_fetch("/api/whitelist");
        this.whitelistFiles = data.whitelist || [];
        this.showWhitelistModal = true;
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
        this.whitelistFiles = [];
      }
    },
    async getWhitelist() {
      try {
        const data = await this.auth_fetch("/api/whitelist");
        this.whitelistFiles = data.whitelist || [];
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
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
        const result = await this.auth_fetch("/api/whitelist", {
          method: "POST",
          body: JSON.stringify({
            file_path: filePath,
          }),
        });
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
          this.showModalComponent(
            "error",
            "白名单添加失败",
            result.message || "未知错误",
            "bi-x-circle"
          );
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
      } finally {
        this.addToWhitelistLoading = false;
      }
    },
    startRename(file, index) {
      // 取消其他正在编辑的项目
      this.unrenamedFiles.forEach((f, i) => {
        if (f.isRenaming && i !== index) {
          this.cancelRename(f, i);
        }
      });

      // 开始重命名 - 使用Vue.set或者重新赋值来触发响应式更新
      this.$set(file, "isRenaming", true);
      this.$set(file, "originalFileName", file.file_name);
      this.$set(file, "newFileName", file.file_name);
      this.$set(file, "renameError", "");
      this.$set(file, "isSubmitting", false);

      // 聚焦到输入框
      this.$nextTick(() => {
        const input = document.getElementById("rename-input-" + index);
        if (input) {
          input.focus();
          input.select();
        }
      });
    },

    cancelRename(file, index) {
      this.$set(file, "isRenaming", false);
      this.$set(file, "newFileName", "");
      this.$set(file, "renameError", "");
      this.$set(file, "isSubmitting", false);
      // 恢复原文件名
      if (file.originalFileName) {
        this.$set(file, "file_name", file.originalFileName);
      }
    },

    async confirmRename(file, index) {
      if (!file.newFileName || file.newFileName.trim() === "") {
        this.$set(file, "renameError", "文件名不能为空");
        return;
      }

      if (file.newFileName === file.originalFileName) {
        this.$set(file, "renameError", "新文件名与原文件名相同");
        return;
      }

      // 简单的文件名验证
      if (!/^[^<>:"/\\|?*]+$/.test(file.newFileName)) {
        this.$set(file, "renameError", "文件名包含非法字符");
        return;
      }

      this.$set(file, "renameError", "");
      this.$set(file, "isSubmitting", true);
      this.renameLoading = true;

      try {
        // 这里调用你的重命名API
        const result = await this.renameFile({
          file_path: file.file_directory,
          file_name: file.originalFileName,
          new_file_name: file.newFileName.trim(),
        });

        if (result.success) {
          // 重命名成功，更新文件信息
          this.$set(file, "file_name", file.newFileName.trim());
          this.$set(file, "isRenaming", false);
          this.$set(file, "newFileName", "");
          this.$set(file, "originalFileName", "");
          // 或者显示成功消息
          this.showSuccess("文件重命名成功", "文件重命名");
        } else {
          this.$set(file, "renameError", result.message || "重命名失败");
        }
      } catch (error) {
        this.$set(file, "renameError", "网络错误，请稍后重试");
        console.error("重命名失败:", error);
      } finally {
        this.$set(file, "isSubmitting", false);
        this.renameLoading = false;
      }
    },
    async renameFile(data) {
      return this.auth_fetch("/api/rename-file", {
        method: "POST",
        body: JSON.stringify(data),
      });
    },
    async deleteFromWhitelist(filePath) {
      this.deleteFromWhitelistLoading = true;

      try {
        const result = await this.auth_fetch("/api/whitelist", {
          method: "DELETE",
          body: JSON.stringify({
            file_path: filePath,
          }),
        });
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
          this.showModalComponent(
            "error",
            "移出白名单失败",
            result.message || "未知错误",
            "bi-x-circle"
          );
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
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
        this.showModalComponent(
          "warning",
          "警告",
          "该路径已在白名单中",
          "bi-x-circle"
        );
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
        const result = await this.auth_fetch("/api/whitelist", {
          method: "POST",
          body: JSON.stringify({ items: this.getNewWhitelistItems() }),
        });
        if (result.success) {
          this.newWhitelistItems = [];
          this.loadSystemStatus();
          this.loadHistory();
          this.whi;
        } else {
          this.showModalComponent(
            "error",
            "批量添加失败",
            result.message || "未知错误",
            "bi-x-circle"
          );
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
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
    async toggleFilter() {
      this.showFilteredOnly = !this.showFilteredOnly;
      await this.loadHistory();
    },
    // 加载正则表达式配置
    async loadRegexPatterns() {
      this.regexLoading = true;

      try {
        const data = await this.auth_fetch("/api/regex-patterns");
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
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
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
        const result = await this.auth_fetch("/api/regex-patterns", {
          method: "POST",
          body: JSON.stringify(this.regexPatterns),
        });
        if (result.success) {
          this.closeRegexModal();
          this.showSuccess("正则配置已保存", "保存成功");
        } else {
          this.regexError = "保存失败: " + result.message;
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "请求失败: 网络错误",
            "bi-x-circle"
          );
        }
        this.regexError = "保存失败: 网络错误";
      } finally {
        this.regexSaving = false;
      }
    },
    triggerImportFile() {
      this.$refs.importFileInput.click();
    },
    triggerImportFile() {
      this.$refs.importFileInput.click();
    },

    // 处理文件导入
    async handleImportFile(event) {
      const file = event.target.files[0];
      if (!file) return;

      // 验证文件类型
      if (!file.name.toLowerCase().endsWith(".json")) {
        this.regexError = "只支持 JSON 格式的配置文件";
        return;
      }

      // 验证文件大小 (限制为 1MB)
      if (file.size > 1024 * 1024) {
        this.regexError = "文件大小不能超过 1MB";
        return;
      }

      this.regexLoading = true;
      this.regexError = "";

      try {
        // 读取文件内容
        const fileContent = await this.readFileAsText(file);
        let configData;

        try {
          configData = JSON.parse(fileContent);
        } catch (parseError) {
          this.regexError = "JSON 文件格式无效";
          return;
        }

        // 验证配置数据结构
        if (!this.validateConfigData(configData)) {
          this.regexError = "配置文件格式不正确，请检查文件内容";
          return;
        }
        const result = await this.auth_fetch("/api/regex-patterns", {
          method: "POST",
          body: JSON.stringify(configData),
        });
        if (result.success) {
          // 成功后刷新数据
          await this.loadRegexPatterns();
          this.showSuccess("配置导入成功", "导入成功");
        } else {
          this.regexError = "导入失败: " + result.message;
        }
      } catch (error) {
        if (error.status === 401) {
          // 鉴权失败逻辑
          this.isAuthenticated = false;
          localStorage.removeItem("access_key");
          this.authError = "未授权或密钥无效";
          this.showModalComponent(
            "error",
            "认证失败",
            "Access Key 无效或已过期，请重新登录。",
            "bi-lock"
          );
        } else {
          this.showModalComponent(
            "error",
            "请求失败",
            "导入失败: 网络错误",
            "bi-x-circle"
          );
        }
        this.regexError = "导入失败: 网络错误";
      } finally {
        this.regexLoading = false;
        // 清空文件输入，以便可以重复选择同一文件
        event.target.value = "";
      }
    },

    // 读取文件内容
    readFileAsText(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.onerror = (e) => reject(new Error("文件读取失败"));
        reader.readAsText(file, "UTF-8");
      });
    },

    // 验证配置数据结构
    validateConfigData(data) {
      if (!data || typeof data !== "object") {
        return false;
      }

      // 检查必要的字段
      if (!data.episode_only || !Array.isArray(data.episode_only)) {
        return false;
      }

      if (!data.season_episode || !Array.isArray(data.season_episode)) {
        return false;
      }

      // 检查数组中的元素是否都是字符串
      const isValidArray = (arr) =>
        arr.every((item) => typeof item === "string");

      return (
        isValidArray(data.episode_only) && isValidArray(data.season_episode)
      );
    },
    showModalComponent(
      type,
      title,
      content,
      icon,
      hasCancel = false,
      callback = null
    ) {
      this.modalType = type;
      this.modalTitle = title;
      this.modalContent = content;
      this.modalIcon = icon;
      this.hasCancel = hasCancel;
      this.confirmCallback = callback;
      this.showModal = true;

      // 添加活动类以触发动画
      setTimeout(() => {
        const modalElement = document.querySelector(".custom-modal");
        if (modalElement) {
          modalElement.classList.add("active");
        }
      }, 10);
    },

    closeModal() {
      this.showModal = false;
    },

    confirmAction() {
      if (this.confirmCallback && typeof this.confirmCallback === "function") {
        this.confirmCallback();
      }
      this.closeModal();
    },
    copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard
          .writeText(text)
          .then(() => {
            this.showSuccess("路径已复制到剪贴板", "复制成功");
          })
          .catch((err) => {
            console.error("Clipboard API 复制失败:", err);
            this.showError("复制失败，请重试", "操作失败");
            // 尝试 fallback
            this.fallbackCopyText(text);
          });
      } else {
        console.warn("Clipboard API 不可用，使用 fallback");
        this.fallbackCopyText(text);
      }
    },

    fallbackCopyText(text) {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "absolute";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        const successful = document.execCommand("copy");
        if (successful) {
          this.showSuccess("路径已复制到剪贴板", "复制成功");
        } else {
          this.showError("复制失败，请手动选择文本", "操作失败");
        }
      } catch (err) {
        console.error("Fallback 复制异常:", err);
        this.showError("复制失败，请手动复制", "操作失败");
      }
      document.body.removeChild(textarea);
    },
  },
});
