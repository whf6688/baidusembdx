import { useState, type FormEvent } from 'react'
import { Button, Field, Input, Spinner } from '@fluentui/react-components'
import { apiPost } from '../../api'

type Props = {
  checking?: boolean
  onAuthenticated: () => void
}

export function LoginPage({ checking = false, onAuthenticated }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入登录账号和密码')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await apiPost<{ username: string }>('/auth/login', {
        username: username.trim(),
        password,
      })
      onAuthenticated()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '登录失败，请稍后再试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-product" aria-label="产品说明">
        <div className="login-brand">
          <span className="login-brand-mark" aria-hidden="true">百</span>
          <span><strong>百度搜索信息流</strong><small>投放管理平台</small></span>
        </div>
        <div className="login-product-copy">
          <h1>百度搜索信息流<br />投放管理平台</h1>
        </div>
        <div aria-hidden="true" />
      </section>

      <section className="login-panel" aria-label="账号登录">
        <div className="login-card">
          <div className="login-card-head">
            <span className="login-mobile-brand">百度搜索信息流投放管理平台</span>
            <h2>登录</h2>
            <p>使用成员管理中对应的登录账号进入系统</p>
          </div>

          {checking ? (
            <div className="login-checking" role="status">
              <Spinner size="small" />
              <span>正在确认登录状态…</span>
            </div>
          ) : (
            <form className="login-form" onSubmit={submit}>
              <Field label="登录账号" required>
                <Input
                  value={username}
                  onChange={(_, data) => setUsername(data.value)}
                  autoComplete="username"
                  autoFocus
                  placeholder="请输入登录账号"
                  disabled={submitting}
                />
              </Field>
              <Field label="密码" required>
                <Input
                  type="password"
                  value={password}
                  onChange={(_, data) => setPassword(data.value)}
                  autoComplete="current-password"
                  placeholder="请输入密码"
                  disabled={submitting}
                />
              </Field>
              {error ? <div className="login-error" role="alert">{error}</div> : null}
              <Button appearance="primary" type="submit" disabled={submitting}>
                {submitting ? '正在登录…' : '登录'}
              </Button>
            </form>
          )}

          <p className="login-help">无法登录时，请联系系统管理员核对账号状态或重置密码。</p>
        </div>
        <p className="login-footer">仅供授权成员使用</p>
      </section>
    </main>
  )
}
