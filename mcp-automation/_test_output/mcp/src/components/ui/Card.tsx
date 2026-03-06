import React from 'react'
import Image from 'next/image'

export type CardProps = {
  image?:     string
  title?:     string
  subtitle?:  string
  badge?:     string
  onClick?:   () => void
  className?: string
  children?:  React.ReactNode
}

export default function Card({
  image,
  title,
  subtitle,
  badge,
  onClick,
  className = '',
  children,
}: CardProps) {
  return (
    <div
      onClick={onClick}
      className={`bg-[#ffffff] rounded-[8px] pt-[0px] pr-[0px] pb-[0px] pl-[0px]  ${className}`}
    >
      {image && (
        <div className="relative w-full h-[2043px] overflow-hidden rounded-[6px] mb-3">
          <Image src={image} fill className="object-cover" alt={title ?? ''} />
        </div>
      )}
      {badge && <span className="inline-block mb-2 px-2 py-0.5 text-xs font-medium bg-[#ffffff]/50 rounded-[6px]">{badge}</span>}
      {title    && <h3 className="font-semibold text-base mb-1">{title}</h3>}
      {subtitle && <p  className="text-sm opacity-70">{subtitle}</p>}
      {children}
    </div>
  )
}
