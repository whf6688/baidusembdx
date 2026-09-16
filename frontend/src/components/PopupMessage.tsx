import { useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

type PopupIntent = 'success' | 'error' | 'warning' | 'info'

function popupRoot() {
  const existing = document.getElementById('global-popup-messages')
  if (existing) return existing
  const root = document.createElement('div')
  root.id = 'global-popup-messages'
  root.className = 'global-popup-messages'
  root.setAttribute('aria-label', '页面提示')
  document.body.appendChild(root)
  return root
}

export function PopupMessage({ intent = 'info', children }: { intent?: PopupIntent; children: ReactNode }) {
  const [visible, setVisible] = useState(true)
  if (!visible) return null
  return createPortal(
    <section className={`popup-message popup-${intent}`} role={intent === 'error' ? 'alert' : 'status'}>
      <div className="popup-message-content">{children}</div>
      <button type="button" className="popup-message-close" aria-label="关闭提示" onClick={() => setVisible(false)}>关闭</button>
    </section>,
    popupRoot(),
  )
}
