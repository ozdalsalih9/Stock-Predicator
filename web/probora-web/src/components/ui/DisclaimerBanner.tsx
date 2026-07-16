import { ShieldCheck } from 'lucide-react'

export function DisclaimerBanner() {
  return (
    <aside className="disclaimer-banner">
      <ShieldCheck size={18} />
      <p><strong>Karar desteği, yatırım tavsiyesi değil.</strong> Probora kişisel portföy önermez; gösterilen değerler olasılık, risk ve model değerlendirmeleridir.</p>
    </aside>
  )
}
