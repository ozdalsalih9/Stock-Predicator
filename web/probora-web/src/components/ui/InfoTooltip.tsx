import { CircleHelp } from 'lucide-react'

export function InfoTooltip() {
  return (
    <span className="info-tooltip">
      <button aria-describedby="why-model-silent" aria-label="Model neden konuşmuyor?"><CircleHelp size={16} /></button>
      <span role="tooltip" id="why-model-silent">
        <strong>Model neden konuşmuyor?</strong>
        Probora, güven eşiği yeterli olmadığında yön sonucu yayınlamaz. Bu bir hata değil, sistemin risk kontrolüdür.
      </span>
    </span>
  )
}
