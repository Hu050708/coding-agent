import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './app/App.vue'
import { router } from './app/router'
import './shared/styles/tokens.css'
import './shared/styles/base.css'

createApp(App).use(createPinia()).use(router).mount('#app')
