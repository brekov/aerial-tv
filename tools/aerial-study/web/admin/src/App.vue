<template>
<div v-if="isMobilePage" class="mobile-shell"><router-view /></div>
<div v-else class="app">
  <aside class="sidebar">
    <div class="brand"><span class="brand-mark">A</span><span>Aerial Study</span></div>
    <div class="nav-label">工作台</div>
    <nav class="nav">
      <router-link to="/admin" exact-active-class="active">概览</router-link>
      <router-link to="/admin/questions" active-class="active">题库</router-link>
      <router-link to="/admin/materials" active-class="active">素材库</router-link>
      <router-link to="/admin/taxonomy" active-class="active">分类管理</router-link>
      <router-link to="/admin/records" active-class="active">答题记录</router-link>
      <router-link to="/admin/wrong" active-class="active">错题本</router-link>
    </nav>
    <div class="nav-label" style="margin-top:18px">设置</div>
    <nav class="nav"><router-link to="/admin/settings">系统设置</router-link></nav>
    <div class="side-foot"><strong>管理员</strong>NAS · Aerial Study v2<br><a href="/admin/logout" style="color:#9db0ca;text-decoration:none">退出登录</a></div>
  </aside>
  <main class="main"><router-view /></main>
  <nav class="mobile-bottom">
    <router-link to="/admin" exact-active-class="active">概览</router-link>
    <router-link to="/admin/questions" active-class="active">题库</router-link>
    <router-link to="/admin/materials" active-class="active">素材</router-link>
    <router-link to="/admin/records" active-class="active">记录</router-link>
  </nav>
</div>
</template>
<script setup>
import { computed } from 'vue'
const isMobilePage = computed(() => location.pathname.startsWith('/m/'))
</script>
