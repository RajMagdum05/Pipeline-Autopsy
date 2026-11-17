import type { ReactNode } from 'react'

export function Alert({ children, tone = 'success' }: { children: ReactNode; tone?: 'success' | 'info' | 'error' }) {
  return <div className={`alert alert--${tone}`} role="status">{children}</div>
}
