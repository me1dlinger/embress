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

    showModal: false,
    modalType: "info",
    modalTitle: "提示",
    modalContent: "这是一条消息",
    modalIcon: "bi-info-circle",
    hasCancel: false,
    confirmCallback: null,
  },

  mounted() {
    this.autoAuthenticate();
  },

  methods: {
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
        }
        this.systemStatus = null;
      } finally {
        this.statusLoading = false;
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
          this.showModalComponent(
            "success",
            "扫描成功",
            "文件扫描已完成，结果已更新。",
            "bi-check-circle"
          );
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
        }
      } finally {
        this.scanLoading = false;
      }
    },

    // 加载扫描历史
    async loadHistory() {
      this.historyLoading = true;

      try {
        const data = await this.auth_fetch("/api/history");

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
        }
        this.history = [];
      } finally {
        this.historyLoading = false;
      }
    },

    // 加载变更记录
    async loadChangeRecords() {
      this.recordsLoading = true;

      try {
        const data = await this.auth_fetch("/api/change-records");

        this.changeRecords = data.records || [];
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
        }
        this.changeRecords = [];
      } finally {
        this.recordsLoading = false;
      }
    },

    // 加载日志文件列表
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
          this.showModalComponent(
            "success",
            "扫描成功",
            "指定路径的扫描操作已完成。",
            "bi-check-circle"
          );
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
          this.showModalComponent(
            "success",
            "回滚成功",
            "指定路径的回滚操作已完成。",
            "bi-check-circle"
          );
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
        }
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
        const response = await this.auth_fetch("/api/whitelist", {
          method: "POST",
          body: JSON.stringify({ items: this.getNewWhitelistItems() }),
        });
        const result = await response.json();

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
          // 保存成功，关闭弹窗
          this.closeRegexModal();
          // 可选：显示成功提示
          this.showModalComponent(
            "success",
            "保存成功",
            "正则配置已成功保存。",
            "bi-check-circle"
          );
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
  },
});
