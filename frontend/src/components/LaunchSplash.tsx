/** Short first-paint logo animation shown on page refresh. */
import { useEffect, useState } from 'react'
import { BrandLogo } from './BrandLogo'

export function LaunchSplash() {
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(false), 1050)
    return () => window.clearTimeout(timer)
  }, [])

  if (!visible) return null

  return (
    <div className="launch-splash" aria-hidden="true">
      <div className="launch-splash__mark">
        <BrandLogo compact />
      </div>
    </div>
  )
}
