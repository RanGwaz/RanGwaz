/** Shared Vibelo brand image. */
interface BrandLogoProps {
  compact?: boolean
  className?: string
}

export function BrandLogo({ compact = false, className = '' }: BrandLogoProps) {
  return (
    <span className={`brand-logo ${compact ? 'brand-logo--compact' : ''} ${className}`.trim()}>
      <img src={compact ? '/vibelo-mark.svg' : '/vibelo-logo.svg'} alt="Vibelo" />
    </span>
  )
}
