import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { clickOutside } from './directives/clickOutside'
import router from './router'
import './styles.css'
import './settings-design.css'

createApp(App)
  .use(createPinia())
  .use(router)
  .directive('click-outside', clickOutside)
  .mount('#app')
