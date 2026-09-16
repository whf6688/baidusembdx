import { createRoot } from 'react-dom/client'
import { FluentProvider, createLightTheme } from '@fluentui/react-components'
import App from './App'
import { commerceBlue, installDesignTokens } from './ui/tokens'
import './ui/foundations.css'
import './ui/components.css'
import './design-system.css'
import './features/accounts/feature.css'
import './features/auto-launch/feature.css'
import './features/reports/feature.css'
import './features/finance/feature.css'
import './features/projects/feature.css'
import './features/members/feature.css'
import './features/strategies/feature.css'
import './features/auth/feature.css'

installDesignTokens(document.documentElement)
const theme = createLightTheme(commerceBlue)
theme.fontFamilyBase = '"Segoe UI Variable", "PingFang SC", "Microsoft YaHei UI", sans-serif'

createRoot(document.getElementById('root')!).render(
  <FluentProvider theme={theme} className="app-provider">
    <App />
  </FluentProvider>,
)
