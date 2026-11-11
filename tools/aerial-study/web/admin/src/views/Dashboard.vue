<template><div>
<div class="page-head"><div><h1>学习内容概览</h1><p class="muted">Aerial Study Guard · 题库、素材、答题记录</p></div></div>
<div class="cards"><div class="card">启用题目<b>{{ stats.active||0 }}</b></div><div class="card">草稿<b>{{ stats.draft||0 }}</b></div><div class="card">素材<b>{{ stats.materials||0 }}</b></div><div class="card">会话<b>{{ stats.sessions||0 }}</b></div></div>
<div class="panel"><h2>快速入口</h2><div class="row"><router-link class="button" to="/admin/materials">上传/扫描素材</router-link><router-link class="button ghost" to="/admin/questions">AI 生成题目</router-link><router-link class="button ghost" to="/admin/wrong">查看易错题</router-link></div></div>
<div v-if="error" class="panel" style="color:#b33">{{ error }}</div>
</div></template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const stats = ref({}); const error = ref('')
onMounted(async () => { try { const d = await api('/api/v1/admin/stats'); stats.value = { ...d, active: d.questions?.active, draft: d.questions?.draft, materials: d.materials, sessions: d.sessions } } catch(e) { error.value = e.message } })
</script>
