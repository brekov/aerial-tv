<template>
<div>
<header class="topbar"><div class="crumb">学习管理 / <b>概览</b></div><div class="search">⌕ <span>搜索题库、素材…</span></div><div class="top-actions"><router-link class="btn ghost" to="/admin/materials">上传素材</router-link><router-link class="btn" to="/admin/generate">AI 生成题目</router-link><div class="avatar">AS</div></div></header>
<div class="content"><div class="page-title"><div><h1>学习内容概览</h1><p>Aerial Study Guard · 题库、素材、答题和错题</p></div><div class="quick-stats"><div class="stat"><span>会话</span><b>{{ stats.sessions||0 }}</b></div><div class="stat"><span>素材</span><b>{{ stats.materials||0 }}</b></div></div></div>
<div class="quick-stats" style="display:grid;grid-template-columns:repeat(4,1fr);margin-bottom:16px"><div class="panel" style="padding:16px"><span class="muted" style="font-size:12px">启用题目</span><div style="font-size:26px;font-weight:700">{{ stats.questions?.active||0 }}</div></div><div class="panel" style="padding:16px"><span class="muted" style="font-size:12px">草稿</span><div style="font-size:26px;font-weight:700">{{ stats.questions?.draft||0 }}</div></div><div class="panel" style="padding:16px"><span class="muted" style="font-size:12px">素材</span><div style="font-size:26px;font-weight:700">{{ stats.materials||0 }}</div></div><div class="panel" style="padding:16px"><span class="muted" style="font-size:12px">答题会话</span><div style="font-size:26px;font-weight:700">{{ stats.sessions||0 }}</div></div></div>
<div class="panel" style="padding:18px"><h2 style="font-size:16px;margin:0 0 12px">快速入口</h2><div class="row"><router-link class="btn" to="/admin/questions">进入题库</router-link><router-link class="btn ghost" to="/admin/materials">素材与二维码</router-link><router-link class="btn ghost" to="/admin/wrong">错题本</router-link><router-link class="btn ghost" to="/admin/records">答题记录</router-link></div></div>
<div v-if="error" class="notice" style="margin-top:14px;color:#b91c1c">{{error}}</div></div>
</div>
</template>
<script setup>
import { ref,onMounted } from 'vue'; import { api } from '../api'
const stats=ref({});const error=ref('')
onMounted(async()=>{try{stats.value=await api('/api/v1/admin/stats')}catch(e){error.value=e.message}})
</script>
