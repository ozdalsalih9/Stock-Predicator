import { Check, Clock3, LockKeyhole } from 'lucide-react'

const steps = [
  { label: 'Veri toplama', state: 'done' },
  { label: 'Model eğitimi', state: 'done' },
  { label: 'Shadow tahmin', state: 'active' },
  { label: '30 günlük sonuçlar', state: 'waiting' },
  { label: '90 günlük sonuçlar', state: 'waiting' },
  { label: 'Promotion değerlendirmesi', state: 'locked' },
] as const

export function ModelJourney() {
  return (
    <ol className="model-journey">
      {steps.map((step, index) => (
        <li className={step.state} key={step.label}>
          <span>{step.state === 'done' ? <Check size={14} /> : step.state === 'locked' ? <LockKeyhole size={13} /> : <Clock3 size={13} />}</span>
          <div><small>0{index + 1}</small><strong>{step.label}</strong></div>
        </li>
      ))}
    </ol>
  )
}
