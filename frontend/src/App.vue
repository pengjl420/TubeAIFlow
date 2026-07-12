<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/">TubeAIFlow</RouterLink>
      <RouterLink class="primary-link" to="/projects/new">新建项目</RouterLink>
    </header>
    <main>
      <RouterView />
    </main>
  </div>
</template>
