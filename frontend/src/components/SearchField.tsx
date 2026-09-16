import { Search20Regular } from '@fluentui/react-icons'

type SearchFieldProps = {
  value: string
  placeholder: string
  ariaLabel?: string
  onChange: (value: string) => void
  onSearch?: () => void
  onClear?: () => void
  disabled?: boolean
  className?: string
}

/** A shared compact search field for all data workspaces. */
export function SearchField({ value, placeholder, ariaLabel = '搜索', onChange, onSearch, onClear, disabled, className = '' }: SearchFieldProps) {
  return <div className={`search-field ${className}`.trim()} role="search">
    <input
      type="search"
      value={value}
      disabled={disabled}
      placeholder={placeholder}
      aria-label={ariaLabel}
      onChange={event => onChange(event.target.value)}
      onKeyDown={event => {
      if (event.key === 'Enter') onSearch?.()
      if (event.key === 'Escape' && value) {
        event.preventDefault()
        if (onClear) onClear()
        else onChange('')
      }
      }}
    />
    <button type="button" className="search-icon-button" aria-label="搜索" title="搜索" disabled={disabled} onClick={() => onSearch?.()}>
      <Search20Regular aria-hidden="true" />
    </button>
  </div>
}
