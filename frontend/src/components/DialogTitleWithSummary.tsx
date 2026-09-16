import type { ReactNode } from 'react'
import { Button, DialogTitle, DialogTrigger } from '@fluentui/react-components'

type DialogTitleWithSummaryProps = {
  children: ReactNode
  summary: ReactNode
}

/** All dialogs use the same title row: a heading followed by a short purpose summary. */
export function DialogTitleWithSummary({ children, summary }: DialogTitleWithSummaryProps) {
  return (
    <DialogTitle
      className="dialog-title-with-summary"
      action={
        <DialogTrigger action="close" disableButtonEnhancement>
          <Button appearance="secondary" size="small">关闭</Button>
        </DialogTrigger>
      }
    >
      <span className="dialog-title-text">{children}</span>
      <small className="dialog-title-summary">{summary}</small>
    </DialogTitle>
  )
}
