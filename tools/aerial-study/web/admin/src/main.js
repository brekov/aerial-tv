import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import Dashboard from './views/Dashboard.vue'
import Taxonomy from './views/Taxonomy.vue'
import Materials from './views/Materials.vue'
import Questions from './views/Questions.vue'
import Records from './views/Records.vue'
import WrongBook from './views/WrongBook.vue'
import MobileUpload from './views/MobileUpload.vue'

const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/admin' },
  { path: '/admin', component: Dashboard },
  { path: '/admin/taxonomy', component: Taxonomy },
  { path: '/admin/materials', component: Materials },
  { path: '/admin/questions', component: Questions },
  { path: '/admin/records', component: Records },
  { path: '/admin/wrong', component: WrongBook },
  { path: '/m/upload/:token', component: MobileUpload },
] })
createApp(App).use(router).mount('#app')
