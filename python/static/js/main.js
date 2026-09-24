new Vue({
  delimiters: ["[[", "]]"],
  el: "#app",
  data: {
    // 认证相关
    isAuthenticated: false,
    accessKey: "",
    authLoading: false,
    authError: "",

    // 选项卡与导航
    activeTab: "dashboard",

    // 主题
    theme: "light",

    // AI 重命名
    showAiModal: false,
    aiStatus: {
      configured: false,
      model: "",
      base_url: "",
      bindings: 0,
      provider_count: 0,
      default_provider: null,
    },
    aiBindings: [],
    newAiPath: "",
    newAiProviderId: "",
    aiLoading: false,

    // AI 供应商
    showProviderModal: false,
    aiProviders: [],
    aiProviderForm: {
      id: null,
      name: "",
      base_url: "",
      api_key: "",
      model: "",
      enabled: true,
      is_default: false,
    },
    aiProviderEditing: false,
    aiTesting: false,
    aiTestResult: null,
    aiSaving: false,

    // 智能整理
    organizeEnabled: false,
    organizeProviderId: "",
    organizeInterval: 3600,
    organizeLoose: [],
    organizeLoading: false,
    organizeToggling: false,
    organizeSaving: false,
    organizeRunning: false,
    organizeHistory: [],
    organizeHistoryLoading: false,
    organizeResetting: false,
    showOrganizeResultModal: false,
    showOrganizeTimeline: false,
    showOrganizeUnprocessed: false,
    organizeResult: null,
    organizeRecords: [],
    organizeRecordsLoading: false,
    organizeRestoring: false,

    // 系统状态
    systemStatus: null,
    // 初始即为加载中：避免 F5 后、首次请求发出前先闪出矮小的空状态导致布局抖动
    statusLoading: true,
    lastScanResult: null,
    lastEffectScanResult: null,

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
      "organize",
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

    showRegexDebugModal: false,
    debugFileName: "",
    debugResults: [],
    debugLoading: false,

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
    pendingConfirmResolve: null,
    showSearchQuery: "",
    filteredShowsChangeList: [],
    showFilteredOnly: false,
  },

  mounted() {
    this.theme = document.documentElement.getAttribute("data-theme") || "light";
    this.applyTheme();
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
    navItems() {
      return [
        { key: "dashboard", label: "仪表板", icon: "bi-speedometer2" },
        { key: "history", label: "扫描历史", icon: "bi-clock-history" },
        { key: "records", label: "变更记录", icon: "bi-list-ul" },
        { key: "logs", label: "日志查看", icon: "bi-file-text" },
      ];
    },
    organizeCachedCount() {
      return this.organizeLoose.filter((item) => item && item.cached).length;
    },
    organizeRecordsActiveCount() {
      return this.organizeRecords.filter((record) => !record.rollback).length;
    },
    organizeResultIsRun() {
      if (!this.organizeResult) return false;
      return (
        this.organizeResult.scan_type === "organize" ||
        (this.organizeResult.milestones || []).length > 0
      );
    },
    // 本次整理中未成功（跳过/失败）的文件：不会写入变更记录，单独展示
    organizeUnprocessedItems() {
      const result = this.organizeResult;
      if (!result || !this.organizeResultIsRun) return [];
      return (result.items || []).filter((item) => item && item.status !== "success");
    },
    organizeRunId() {
      const result = this.organizeResult;
      if (!result || !result.run_id) return null;
      return result.run_id;
    },
    organizeRecordsScoped() {
      const result = this.organizeResult;
      if (!result) return false;
      return (result.items || []).length > 0 || !!result.path;
    },
    organizeRecordGroups() {
      const groups = {};
      this.organizeRecords.forEach((record) => {
        const showKey = `${record.media_type || "未分类"} · ${record.show_name || "未分类"}`;
        if (!groups[showKey]) {
          groups[showKey] = {
            media_type: record.media_type,
            show_name: record.show_name,
            seasons: {},
            total: 0,
            active: 0,
          };
        }
        const group = groups[showKey];
        const seasonKey = record.season_name || "未知季度";
        if (!group.seasons[seasonKey]) {
          group.seasons[seasonKey] = {
            season_name: record.season_name,
            records: [],
            active: 0,
          };
        }
        const season = group.seasons[seasonKey];
        season.records.push(record);
        group.total += 1;
        if (!record.rollback) {
          group.active += 1;
          season.active += 1;
        }
      });
      return groups;
    },
    tabMeta() {
      return {
        dashboard: "仪表板",
        history: "扫描历史",
        records: "变更记录",
        logs: "日志查看",
      }[this.activeTab];
    },
  },
  methods: {
    selectTab(key) {
      this.activeTab = key;
    },
    applyTheme() {
      document.documentElement.setAttribute("data-theme", this.theme);
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute("content", this.theme === "dark" ? "#0f1013" : "#f7f7f8");
    },
    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      localStorage.setItem("theme", this.theme);
      this.applyTheme();
    },
    async showAiConfig() {
      this.showAiModal = true;
      await Promise.all([
        this.loadAiStatus(),
        this.loadAiProviders(),
        this.loadSystemStatus(),
      ]);
      await this.loadOrganizeData();
    },
    closeAiConfig() {
      this.showAiModal = false;
      this.newAiPath = "";
    },
    async loadAiStatus() {
      try {
        const [status, bindings] = await Promise.all([
          this.auth_fetch("/api/ai/status"),
          this.auth_fetch("/api/ai/bindings"),
        ]);
        this.aiStatus = status;
        this.aiBindings = bindings.bindings || [];
      } catch (error) {
        this.showError("加载 AI 配置失败", "AI");
      }
    },
    async addAiBinding() {
      const path = this.newAiPath.trim();
      if (!path) return;
      this.aiLoading = true;
      try {
        const result = await this.auth_fetch("/api/ai/bindings", {
          method: "POST",
          body: JSON.stringify({ path, provider_id: this.newAiProviderId || null }),
        });
        if (result.success) {
          this.newAiPath = "";
          this.showSuccess(result.message || "绑定成功", "AI");
          await this.loadAiStatus();
        } else {
          this.showError(result.message || "绑定失败", "AI");
        }
      } catch (error) {
        this.showError("绑定失败：网络错误", "AI");
      } finally {
        this.aiLoading = false;
      }
    },
    async removeAiBinding(path) {
      this.aiLoading = true;
      try {
        const result = await this.auth_fetch("/api/ai/bindings", {
          method: "DELETE",
          body: JSON.stringify({ path }),
        });
        if (result.success) {
          this.showSuccess(result.message || "已解除绑定", "AI");
          await this.loadAiStatus();
        } else {
          this.showError(result.message || "解除失败", "AI");
        }
      } catch (error) {
        this.showError("解除失败：网络错误", "AI");
      } finally {
        this.aiLoading = false;
      }
    },
    providerName(id) {
      if (!id) return "默认供应商";
      const found = this.aiProviders.find((p) => p.id === id);
      return found ? found.name : "已删除的供应商";
    },
    async showProviderConfig() {
      this.showProviderModal = true;
      this.aiTestResult = null;
      await Promise.all([this.loadAiProviders(), this.loadAiStatus()]);
    },
    closeProviderConfig() {
      this.showProviderModal = false;
      this.resetAiProviderForm();
      this.aiTestResult = null;
    },
    newAiProvider() {
      this.aiProviderEditing = true;
      this.aiTestResult = null;
      this.aiProviderForm = {
        id: null,
        name: "",
        base_url: "",
        api_key: "",
        model: "",
        enabled: true,
        is_default: this.aiProviders.length === 0,
      };
    },
    editAiProvider(provider) {
      this.aiProviderEditing = true;
      this.aiTestResult = null;
      this.aiProviderForm = {
        id: provider.id,
        name: provider.name,
        base_url: provider.base_url,
        api_key: "",
        model: provider.model || "",
        enabled: provider.enabled,
        is_default: provider.is_default,
      };
    },
    resetAiProviderForm() {
      this.aiProviderEditing = false;
      this.aiProviderForm = {
        id: null,
        name: "",
        base_url: "",
        api_key: "",
        model: "",
        enabled: true,
        is_default: false,
      };
    },
    async loadAiProviders() {
      try {
        const data = await this.auth_fetch("/api/ai/providers");
        this.aiProviders = data.providers || [];
      } catch (error) {
        this.showError("加载供应商失败", "AI");
      }
    },
    async saveAiProvider() {
      if (!this.aiProviderForm.name || !this.aiProviderForm.base_url) return;
      this.aiSaving = true;
      try {
        const result = await this.auth_fetch("/api/ai/providers", {
          method: "POST",
          body: JSON.stringify(this.aiProviderForm),
        });
        if (result.success) {
          this.showSuccess(result.message || "已保存", "AI");
          this.resetAiProviderForm();
          await Promise.all([this.loadAiProviders(), this.loadAiStatus()]);
        } else {
          this.showError(result.message || "保存失败", "AI");
        }
      } catch (error) {
        this.showError("保存失败：网络错误", "AI");
      } finally {
        this.aiSaving = false;
      }
    },
    async deleteAiProvider(provider) {
      this.aiSaving = true;
      try {
        const result = await this.auth_fetch("/api/ai/providers", {
          method: "DELETE",
          body: JSON.stringify({ id: provider.id }),
        });
        if (result.success) {
          this.showSuccess(result.message || "已删除", "AI");
          await Promise.all([this.loadAiProviders(), this.loadAiStatus()]);
        } else {
          this.showError(result.message || "删除失败", "AI");
        }
      } catch (error) {
        this.showError("删除失败：网络错误", "AI");
      } finally {
        this.aiSaving = false;
      }
    },
    async setDefaultProvider(provider) {
      this.aiSaving = true;
      try {
        const result = await this.auth_fetch("/api/ai/providers", {
          method: "POST",
          body: JSON.stringify({
            id: provider.id,
            name: provider.name,
            base_url: provider.base_url,
            model: provider.model,
            enabled: provider.enabled,
            is_default: true,
          }),
        });
        if (result.success) {
          this.showSuccess("已设为默认供应商", "AI");
          await Promise.all([this.loadAiProviders(), this.loadAiStatus()]);
        } else {
          this.showError(result.message || "设置失败", "AI");
        }
      } catch (error) {
        this.showError("设置失败：网络错误", "AI");
      } finally {
        this.aiSaving = false;
      }
    },
    async testAiProvider(target) {
      if (!target || !target.base_url) {
        this.aiTestResult = { ok: false, message: "请先填写 Base URL" };
        return;
      }
      this.aiTesting = true;
      this.aiTestResult = null;
      try {
        const result = await this.auth_fetch("/api/ai/providers/test", {
          method: "POST",
          body: JSON.stringify({
            id: target.id || null,
            base_url: target.base_url,
            model: target.model || null,
            api_key: target.api_key || "",
          }),
        });
        this.aiTestResult = {
          ok: !!result.success,
          message: result.message || (result.success ? "连接成功" : "连接失败"),
        };
      } catch (error) {
        this.aiTestResult = { ok: false, message: "测试失败：网络错误" };
      } finally {
        this.aiTesting = false;
      }
    },
    syncOrganizeState(data) {
      if (!data) return;
      this.organizeEnabled = !!data.organize_enabled;
      if (data.organize_interval) {
        this.organizeInterval = data.organize_interval;
      }
      this.organizeProviderId =
        data.organize_provider_id === null || data.organize_provider_id === undefined
          ? ""
          : data.organize_provider_id;
    },
    async loadOrganizeData() {
      await Promise.all([this.loadOrganizePreview(), this.loadOrganizeHistory()]);
    },
    async loadOrganizePreview() {
      this.organizeLoading = true;
      try {
        const data = await this.auth_fetch("/api/organize/preview");
        this.organizeLoose = data.files || [];
      } catch (error) {
        this.showError("加载待整理文件失败", "智能整理");
      } finally {
        this.organizeLoading = false;
      }
    },
    async resetOrganizeCache() {
      this.organizeResetting = true;
      try {
        const result = await this.auth_fetch("/api/organize/reset", {
          method: "POST",
        });
        if (result.success) {
          this.showSuccess(result.message || "已清空整理缓存", "智能整理");
          await this.loadOrganizePreview();
        } else {
          this.showError(result.message || "操作失败", "智能整理");
        }
      } catch (error) {
        this.showError("操作失败：网络错误", "智能整理");
      } finally {
        this.organizeResetting = false;
      }
    },
    async loadOrganizeHistory() {
      this.organizeHistoryLoading = true;
      try {
        const data = await this.auth_fetch("/api/organize/history?limit=20");
        this.organizeHistory = data.history || [];
      } catch (error) {
        this.organizeHistory = [];
      } finally {
        this.organizeHistoryLoading = false;
      }
    },
    async toggleOrganize(enabled) {
      this.organizeToggling = true;
      try {
        const result = await this.auth_fetch("/api/organize/toggle", {
          method: "POST",
          body: JSON.stringify({ enabled }),
        });
        if (result.success) {
          this.showSuccess(result.message || "已更新", "智能整理");
          await this.loadSystemStatus();
          await this.loadOrganizePreview();
          if (enabled) {
            await this.loadOrganizeHistory();
          }
        } else {
          this.showError(result.message || "切换失败", "智能整理");
        }
      } catch (error) {
        this.showError("切换失败：网络错误", "智能整理");
      } finally {
        this.organizeToggling = false;
      }
    },
    async saveOrganizeProvider() {
      try {
        const result = await this.auth_fetch("/api/organize/provider", {
          method: "POST",
          body: JSON.stringify({
            provider_id: this.organizeProviderId === "" ? null : this.organizeProviderId,
          }),
        });
        if (result.success) {
          this.showSuccess(result.message || "已更新", "智能整理");
          await this.loadSystemStatus();
        } else {
          this.showError(result.message || "保存失败", "智能整理");
        }
      } catch (error) {
        this.showError("保存失败：网络错误", "智能整理");
      }
    },
    async saveOrganizeInterval() {
      const seconds = parseInt(this.organizeInterval, 10);
      if (!seconds || seconds < 60 || seconds > 86400) {
        this.showError("间隔需在 60-86400 秒之间", "智能整理");
        return;
      }
      this.organizeSaving = true;
      try {
        const result = await this.auth_fetch("/api/organize/interval", {
          method: "POST",
          body: JSON.stringify({ interval: seconds }),
        });
        if (result.success) {
          this.showSuccess(result.message || "已更新", "智能整理");
          await this.loadSystemStatus();
        } else {
          this.showError(result.message || "保存失败", "智能整理");
        }
      } catch (error) {
        this.showError("保存失败：网络错误", "智能整理");
      } finally {
        this.organizeSaving = false;
      }
    },
    async runOrganizeNow() {
      this.organizeRunning = true;
      try {
        const result = await this.auth_fetch("/api/organize/run", {
          method: "POST",
        });
        const data = result.result || {};
        if (result.success) {
          this.showSuccess(
            `整理完成：移动 ${data.moved || 0} 个，跳过 ${data.skipped || 0} 个`,
            "智能整理"
          );
        } else {
          this.showError(result.message || "整理失败", "智能整理");
        }
        // 无论成功失败都展示明细，便于排查
        this.showOrganizeResult(data);
        this.loadHistory();
        this.loadChangeRecords();
        await this.loadSystemStatus();
        await this.loadOrganizePreview();
        await this.loadOrganizeHistory();
      } catch (error) {
        this.showError("整理失败：网络错误", "智能整理");
      } finally {
        this.organizeRunning = false;
      }
    },
    showOrganizeResult(record) {
      if (!record) return;
      this.organizeResult = record;
      this.showOrganizeTimeline = false;
      this.showOrganizeUnprocessed = false;
      this.showOrganizeResultModal = true;
      this.loadOrganizeRecords();
    },
    closeOrganizeResult() {
      this.showOrganizeResultModal = false;
      this.organizeResult = null;
      this.showOrganizeTimeline = false;
      this.showOrganizeUnprocessed = false;
    },
    async loadOrganizeRecords() {
      this.organizeRecordsLoading = true;
      try {
        const runId = this.organizeRunId;
        const url = runId
          ? `/api/organize/records?run_id=${encodeURIComponent(runId)}`
          : "/api/organize/records";
        const data = await this.auth_fetch(url);
        this.organizeRecords = runId
          ? data.records || []
          : this.filterLegacyRecords(data.records || []);
      } catch (error) {
        this.organizeRecords = [];
      } finally {
        this.organizeRecordsLoading = false;
      }
    },
    // 历史遗留数据（没有 run_id）无法按任务筛选，退化为按本次结果的文件路径匹配
    filterLegacyRecords(records) {
      const result = this.organizeResult;
      if (!result) return records;
      const normalize = (value) => String(value || "").replace(/\\/g, "/");
      const targets = new Set();
      (result.items || []).forEach((item) => {
        if (item && item.to) targets.add(normalize(item.to));
      });
      if (targets.size) {
        return records.filter((record) => {
          return (
            targets.has(normalize(record.relative_path || record.path)) ||
            targets.has(normalize(record.path))
          );
        });
      }
      if (result.path) {
        // 从「变更记录」直接打开单条旧记录时，仅展示该条
        return records.filter((record) => normalize(record.path) === normalize(result.path));
      }
      // 整理运行结果但没有成功变更：本次没有变更记录
      return this.organizeResultIsRun ? [] : records;
    },
    async restoreOrganize(scope, show, season, record) {
      const payload = { scope };
      if (this.organizeRunId) {
        payload.run_id = this.organizeRunId;
      }
      let label = "该剧集";
      if (scope === "file") {
        payload.path = record.path;
        label = record.original || "该文件";
      } else if (scope === "season") {
        payload.media_type = show.media_type;
        payload.show_name = show.show_name;
        payload.season_name = season.season_name;
        label = `${show.show_name || ""} ${season.season_name || ""}`.trim() || "该季";
      } else {
        payload.media_type = show.media_type;
        payload.show_name = show.show_name;
      }
      const confirmed = await this.confirm({
        title: "还原 AI 整理结果",
        message: `确认还原「${label}」的 AI 整理结果？文件将移回整理前的位置。`,
        danger: true,
      });
      if (!confirmed) {
        return;
      }
      this.organizeRestoring = true;
      try {
        const result = await this.auth_fetch("/api/organize/restore", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (result.success) {
          this.showSuccess(
            `已还原 ${result.restored || 0} 个文件${result.skipped ? `，跳过 ${result.skipped} 个` : ""}`,
            "智能整理"
          );
        } else {
          this.showError(result.message || "还原失败", "智能整理");
        }
        await Promise.all([this.loadOrganizeRecords(), this.loadOrganizePreview()]);
        this.loadHistory();
        this.loadChangeRecords();
      } catch (error) {
        this.showError("还原失败：网络错误", "智能整理");
      } finally {
        this.organizeRestoring = false;
      }
    },
    refreshActive() {
      const loaders = {
        dashboard: () => this.loadSystemStatus(),
        history: () => this.loadHistory(),
        records: () => this.loadChangeRecords(),
        logs: () => this.loadLogFiles(),
      };
      (loaders[this.activeTab] || loaders.dashboard)();
    },
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

    confirm(options = {}) {
      return new Promise((resolve) => {
        this.pendingConfirmResolve = resolve;
        this.showModalComponent(
          options.danger ? "warning" : "info",
          options.title || "确认操作",
          options.message || "",
          options.danger ? "bi-exclamation-triangle" : "bi-question-circle",
          true,
          () => this.settleConfirm(true)
        );
      });
    },

    settleConfirm(result) {
      const resolve = this.pendingConfirmResolve;
      this.pendingConfirmResolve = null;
      if (typeof resolve === "function") {
        resolve(result);
      }
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
        this.syncOrganizeState(data);
        if (data.last_scan) {
          this.lastScanResult = data.last_scan;
        }
        if (data.last_effect_scan) {
          this.lastEffectScanResult = data.last_effect_scan;
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
          await this.loadShowRecords();
        } else {
          // 加载节目列表
          const data = await this.auth_fetch("/api/change-records");
          this.showsChangeList = data.shows || [];
          this.filteredShowsChangeList = [...this.showsChangeList];
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
        this.filteredShowsChangeList = []; // 重置筛选列表
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
    goBackToShows() {
      this.selectedShow = {
        media_type: null,
        show_name: null,
      };
      this.selectedShowRecords = [];
      this.selectedTypeFilter = "all";
      this.groupBy = "type";
      this.showSearchQuery = ""; // 清除搜索
      this.filteredShowsChangeList = [...this.showsChangeList]; // 重置筛选列表
      this.loadChangeRecords();
    },
    getTypeIcon(type) {
      const iconMap = {
        rename: "bi-file-earmark-text text-primary",
        organize: "bi-magic text-info",
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
        organize: "智能整理",
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
        const data = await this.auth_fetch("/api/rollback", {
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
    parsePath(path) {
      if (!path) return { file_name: "", file_directory: "" };

      // 处理路径分隔符（兼容Windows和Linux）
      const normalizedPath = path.replace(/\\/g, "/");
      const lastSlashIndex = normalizedPath.lastIndexOf("/");

      if (lastSlashIndex === -1) {
        // 只有文件名，没有目录路径
        return {
          file_name: path,
          file_directory: "",
        };
      }

      return {
        file_name: normalizedPath.substring(lastSlashIndex + 1),
        file_directory: normalizedPath.substring(0, lastSlashIndex),
      };
    },

    // 修改addNewWhitelist方法
    addNewWhitelist() {
      const path = this.newWhitelistPath.trim();
      if (!path) return;

      // 检查是否已存在
      const exists =
        this.whitelistFiles.some((file) => file.path === path) ||
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

      // 解析路径信息
      const pathInfo = this.parsePath(path);

      this.newWhitelistItems.push({
        path: path,
        type: this.newWhitelistType,
        file_name: pathInfo.file_name,
        file_directory: pathInfo.file_directory,
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
        file_name: item.file_name,
        file_directory: item.file_directory,
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
    openRegexDebugModal() {
      this.showRegexDebugModal = true;
      this.debugFileName = "";
      this.debugResults = [];
    },

    closeRegexDebugModal() {
      this.showRegexDebugModal = false;
    },

    createRegex(pattern) {
      try {
        return new RegExp(pattern, "i");
      } catch (e) {
        // 如果正则表达式无效，尝试转义特殊字符
        try {
          const escaped = pattern.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&");
          return new RegExp(escaped, "i");
        } catch (e) {
          console.error("无法创建正则表达式:", pattern);
          return null;
        }
      }
    },

    runDebug() {
      if (!this.debugFileName) return;

      this.debugLoading = true;
      this.debugResults = [];

      try {
        // 测试所有正则表达式
        const allPatterns = [
          ...this.regexPatterns.episode_only.map((p) => ({
            type: "episode_only",
            pattern: p,
          })),
          ...this.regexPatterns.season_episode.map((p) => ({
            type: "season_episode",
            pattern: p,
          })),
        ];

        // 先收集所有结果
        let results = [];
        for (const item of allPatterns) {
          const regex = this.createRegex(item.pattern);
          const result = regex ? this.debugFileName.match(regex) : null;

          results.push({
            type: item.type,
            pattern: item.pattern,
            matched: result !== null,
            fullMatch: result ? result[0] : null,
            groups: result ? result.slice(1) : [],
            error: !regex ? "无效的正则表达式" : null,
            // 添加排序权重
            sortWeight: result ? result[0].length * 10 + result.length : 0,
          });
        }

        // 对结果进行排序 - 匹配成功的优先，然后按匹配长度和捕获组数量排序
        this.debugResults = results.sort((a, b) => {
          if (a.matched !== b.matched) {
            return b.matched - a.matched; // 匹配的排在前面
          }
          if (a.matched && b.matched) {
            return b.sortWeight - a.sortWeight; // 匹配长度更长的优先
          }
          return 0;
        });
      } catch (error) {
        console.error("调试出错:", error);
        this.showError("调试过程中出错", "调试错误");
      } finally {
        this.debugLoading = false;

        // 自动滚动到顶部
        this.$nextTick(() => {
          const container = document.querySelector(".debug-results");
          if (container) {
            container.scrollTop = 0;
          }
        });
      }
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
    filterShows() {
      if (!this.showSearchQuery) {
        this.filteredShowsChangeList = this.showsChangeList;
        return;
      }

      const query = this.showSearchQuery.toLowerCase();
      this.filteredShowsChangeList = this.showsChangeList.filter(
        (show) =>
          show.show_name.toLowerCase().includes(query) ||
          show.media_type.toLowerCase().includes(query)
      );
    },
    clearSearch() {
      this.showSearchQuery = "";
      this.filteredShowsChangeList = this.showsChangeList;
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
      // 取消/关闭时让等待中的 confirm() 返回 false
      this.settleConfirm(false);
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
