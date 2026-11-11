<template>
  <div v-if="mobile" class="mobile-shell"><router-view /></div>
  <div v-else class="shell">
    <aside class="sidebar">
      <div class="brand">Aerial Study</div>
      <nav>
        <router-link to="/admin">概览</router-link>
        <router-link to="/admin/taxonomy">分类</router-link>
        <router-link to="/admin/materials">素材</router-link>
        <router-link to="/admin/questions">题库</router-link>
        <router-link to="/admin/records">答题记录</router-link>
        <router-link to="/admin/wrong">错题本</router-link>
      </nav>
      <a class="ghost" href="/admin/logout">退出</a>
    </aside>
    <main class="content"><router-view /></main>
  </div>
</template>
<script setup>
import { computed } from 'vue'
const mobile = computed(() => location.pathname.startsWith('/m/'))
</script>
