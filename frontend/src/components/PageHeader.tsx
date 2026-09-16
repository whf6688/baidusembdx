import { createContext, useContext, type ReactNode } from 'react'

export const WorkspaceHeaderContext = createContext<ReactNode>(null)

type Props = {
  title: string
  /** Retained for page-call compatibility; descriptions no longer render in the title row. */
  description?: string
  summary?: ReactNode
  action?: ReactNode
}

/** Page identity stays compact; actions and reminders occupy the opposite edge. */
export function PageHeader({ title, description, summary, action }: Props) {
  const workspaceAction = useContext(WorkspaceHeaderContext)
  return <section className="page-heading compact"><div><h1>{title}</h1>{summary ? <span className="page-heading-summary">{summary}</span> : null}{description ? <p>{description}</p> : null}</div><div className="page-heading-actions">{action}{workspaceAction}</div></section>
}
