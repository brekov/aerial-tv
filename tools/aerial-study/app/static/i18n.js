/* Small Chinese/English layer for the internal admin page. No build step, no CDN.
 * Default is Chinese when the browser is Chinese; the toggle stores the choice in localStorage.
 * Technical values, model ids, prompts and user-entered text are deliberately left alone.
 */
(() => {
  "use strict";

  const ZH = {
    // common
    "Aerial Study Guard": "Aerial 学习守护",
    "Study Guard admin · Aerial": "学习守护管理 · Aerial",
    "Sign in · Aerial Study Guard": "登录 · Aerial 学习守护",
    "Admin sign-in": "管理员登录",
    "Password": "密码",
    "Sign in": "登录",
    "Sign out": "退出登录",
    "LAN-only service. The password comes from the container environment.":
      "仅限局域网。密码来自容器环境变量。",
    "Admin is disabled. Set": "管理页已禁用。请设置",
    "in": "在",
    "and restart the container.": "后重启容器。",
    "wrong password": "密码错误",
    "not signed in": "未登录",

    // header
    "Aerial Study Guard admin": "Aerial 学习守护管理",
    "TV quiz material, AI drafts and speech-to-text · admin session expires after ADMIN_SESSION_HOURS":
      "电视答题素材、AI 草稿和语音识别 · 管理会话按 ADMIN_SESSION_HOURS 过期",
    "TV token required": "电视 Token 已启用",
    "TV token disabled": "电视 Token 未启用",
    "AI ready": "AI 可用",
    "AI not configured": "AI 未配置",

    // stats
    "Active": "启用",
    "Draft": "草稿",
    "Reviewed": "已审核",
    "Disabled": "停用",
    "Materials": "素材",
    "Sessions": "答题会话",
    "needed per session": "每轮需要",
    "AI output lands here": "AI 生成的草稿会出现在这里",
    "ready to activate": "可启用",
    "hidden from sessions": "不会进入抽题",
    "images stored by sha256": "图片按 sha256 存储",
    "quiz attempts recorded": "已记录的答题尝试",

    // materials
    "1 · Materials": "1 · 素材",
    "PNG / JPEG / WebP · deduplicated by sha256": "PNG / JPEG / WebP · 按 sha256 去重",
    "Title (optional)": "标题（可选）",
    "Upload": "上传",
    "No material yet. Upload an image first, then create or generate questions.":
      "还没有素材。先上传图片，再创建或生成题目。",

    // manual
    "2 · Manual draft": "2 · 手动草稿",
    "works without any AI key": "不需要 AI Key",
    "Prompt": "题干",
    "Answer": "答案",
    "What is this?": "请读出图中的词语",
    "apple (alternatives: apple|apples)": "苹果（多个答案用 | 分隔）",
    "Image": "图片",
    "— no image (cannot activate word_image) —": "— 无图片（看图识字不能启用）—",
    "Language": "语言",
    "Chinese (zh)": "中文 (zh)",
    "English (en)": "英文 (en)",
    "Difficulty 1–5": "难度 1–5",
    "Initial status": "初始状态",
    "Create draft question": "创建草稿题",
    "draft": "草稿",
    "reviewed": "已审核",
    "active": "启用",
    "disabled": "停用",
    "succeeded": "成功",
    "failed": "失败",
    "running": "运行中",
    "pending": "等待中",
    "finished": "已完成",
    "expired": "已过期",
    "yes": "是",
    "no": "否",

    // generate
    "3 · AI generation": "3 · AI 出题",
    "creates drafts only, never activates": "只生成草稿，不会自动启用",
    "Default provider": "默认 Provider",
    "has no API key (env only).": "没有 API Key（只从环境变量读取）。",
    "Manual drafts still work; add": "手动草稿仍然可用；在",
    "or": "或",
    "in": "在",
    "and restart to enable vision generation.": "后重启以启用视觉出题。",
    "Source image": "源图片",
    "Provider": "Provider",
    "Question count": "题目数量",
    "Generate drafts": "生成草稿",
    "Job": "任务",
    "Status": "状态",
    "Provider / model": "Provider / 模型",
    "Created": "创建时间",
    "Result": "结果",
    "draft ids": "草稿 ID",
    "No jobs yet.": "还没有生成任务。",

    // questions
    "4 · Questions": "4 · 题库",
    "all": "全部",
    "prompt / answer": "题干 / 答案",
    "Search": "搜索",
    "question(s) match. Activating a word_image requires an attached image.":
      "道题匹配。启用看图识字题必须关联图片。",
    "Edit question": "编辑题目",
    "— no image —": "— 无图片 —",
    "Difficulty": "难度",
    "Change note": "修改说明",
    "why this edit": "为什么修改",
    "Save revision": "保存新版本",
    "Cancel": "取消",
    "ID": "ID",
    "Rev": "版本",
    "Source": "来源",
    "Actions": "操作",
    "none": "无",
    "Edit": "编辑",
    "History": "历史",
    "Activate": "启用",
    "Review": "标记已审核",
    "Disable": "停用",
    "No questions match this filter.": "没有匹配的题目。",
    "Question history": "题目历史",
    "Close": "关闭",
    "Changed by": "修改人",
    "Note": "说明",
    "At": "时间",

    // history / sessions
    "5 · Revision history": "5 · 修改历史",
    "latest 30 changes": "最近 30 次修改",
    "No revisions yet.": "还没有修改记录。",
    "6 · Quiz sessions": "6 · 答题会话",
    "wrong answer restarts the run": "答错会重新开始一轮",
    "Progress": "进度",
    "Correct / wrong": "正确 / 错误",
    "Restarts": "重开次数",
    "Attempts": "尝试次数",
    "Details": "详情",
    "No quiz session yet.": "还没有答题会话。",
    "Session attempts": "会话答题记录",
    "attempt": "尝试",
    "Yes": "是",
    "No": "否",

    // providers
    "7 · AI providers & ASR": "7 · AI Provider 与语音识别",
    "keys are read from env only · never returned or logged":
      "Key 只从环境变量读取 · 不会返回或记录",
    "key from env": "Key 来自环境变量",
    "no key": "无 Key",
    "Base URL": "Base URL",
    "Model": "模型",
    "Auth header name": "鉴权 Header 名称",
    "Set": "请设置",
    "Authorization headers are sent as": "Authorization Header 会以",
    "other header names get the raw key.": "其他 Header 名称直接使用原始 Key。",
    "Save": "保存",
    "routing": "路由",
    "Default provider": "默认 Provider",
    "Allow optional AI text judging when exact match fails":
      "精确匹配失败时允许 AI 文本判题",
    "Save settings": "保存设置",
    "ASR": "语音识别",
    "model": "模型",
    "available": "可用",
    "faster-whisper not installed": "未安装 faster-whisper",
    "loaded": "已加载",
    "lazy (loads on first request)": "懒加载（首次请求时加载）",
    "queue": "队列",
    "language": "语言",
    "CPU-only, short utterances. First request after start downloads the model if absent.":
      "仅 CPU，适合短句。启动后第一次请求会加载模型（如果本地没有）。",
    "Environment": "环境变量",
    "Changing provider routing here persists in SQLite. API keys and ASR sizing stay in":
      "这里修改的 Provider 路由保存在 SQLite；API Key 和 ASR 参数仍在",
    ".env": ".env",

    // toasts in admin.js
    "Choose an image first": "请先选择图片",
    "Already uploaded (same sha256)": "已上传过（sha256 相同）",
    "Material uploaded": "素材已上传",
    "Draft question created": "草稿题已创建",
    "Upload an image first": "请先上传图片",
    "Starting generation…": "正在开始生成…",
    "Generation failed": "生成失败",
    "Generation job queued (draft questions only)": "生成任务已排队（只生成草稿）",
    "Settings saved": "设置已保存",
    "routing saved": "路由已保存",
    "Question": "题目",
    "updated (new revision)": "已更新（新版本）",
    "activated in admin": "在管理页启用",
    "reviewed in admin": "在管理页标记已审核",
    "disabled in admin": "在管理页停用",
  };

  const DYNAMIC = [
    [/^Sign in · (.*)$/, "登录 · $1"],
    [/^Admin sign-in · (.*)$/, "管理员登录 · $1"],
    [/^Study Guard admin · (.*)$/, "学习守护管理 · $1"],
    [/^needed per session: (\d+)$/, "每轮需要：$1"],
    [/^latest (\d+) changes$/, "最近 $1 次修改"],
  ];
  const original = new WeakMap();
  const savedLang = localStorage.getItem("study_lang");
  // Prefer Chinese for this household unless the user explicitly chose English.
  let lang = savedLang === "en" ? "en" : "zh";

  const tr = (text) => {
    if (lang !== "zh") return text;
    return ZH[text] || text;
  };

  const skipped = (node) => {
    const el = node.parentElement;
    if (!el) return true;
    if (el.closest("script, style, code, pre, textarea, input")) return true;
    if (el.closest("td") && !el.closest(".badge, .actions")) return true;
    return false;
  };

  const translateNode = (node) => {
    if (lang !== "zh" || skipped(node)) return;
    const raw = node.nodeValue || "";
    const trimmed = raw.trim();
    if (!trimmed) return;
    let translated = ZH[trimmed];
    if (!translated) {
      for (const [pattern, replacement] of DYNAMIC) {
        if (pattern.test(trimmed)) {
          translated = trimmed.replace(pattern, replacement);
          break;
        }
      }
    }
    if (!translated) return;
    const start = raw.indexOf(trimmed);
    node.nodeValue = raw.slice(0, start) + translated + raw.slice(start + trimmed.length);
  };

  function translateDom(root = document.body) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) translateNode(walker.currentNode);
    root.querySelectorAll("[placeholder], [title], [aria-label]").forEach((el) => {
      for (const attr of ["placeholder", "title", "aria-label"]) {
        const value = el.getAttribute(attr);
        if (value && ZH[value.trim()]) el.setAttribute(attr, ZH[value.trim()]);
      }
    });
    document.documentElement.lang = lang;
    const toggle = document.getElementById("lang-toggle");
    if (toggle) toggle.textContent = lang === "zh" ? "English" : "中文";
    if (lang === "zh") {
      document.title = document.title
        .replace("Aerial Study Guard", "Aerial 学习守护")
        .replace("Study Guard admin", "学习守护管理")
        .replace("Sign in", "登录");
    }
  }

  function setLang(next) {
    lang = next === "en" ? "en" : "zh";
    localStorage.setItem("study_lang", lang);
    location.reload();
  }

  document.addEventListener("DOMContentLoaded", () => {
    translateDom();
    const toggle = document.getElementById("lang-toggle");
    if (toggle) {
      toggle.textContent = lang === "zh" ? "English" : "中文";
      toggle.addEventListener("click", () => setLang(lang === "zh" ? "en" : "zh"));
    }
  });

  window.studyTranslate = tr;
  window.studyTranslateDom = translateDom;
})();
