<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/">TubeAIFlow</RouterLink>
      <nav class="topbar-actions">
        <RouterLink class="secondary-button" to="/settings">系统设置</RouterLink>
        <RouterLink class="primary-link" to="/projects/new">新建项目</RouterLink>
      </nav>
    </header>
    <main><RouterView /></main>
  </div>
</template>
