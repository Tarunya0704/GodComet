import React from 'react'

export type BadgeProps = {
  label:      string
  color?:     'default' | 'primary'
  size?:      'sm' | 'md'
  className?: string
}

const colorStyles: Record<NonNullable<BadgeProps['color']>, string> = {
  default: 'bg-[#e5e7eb] text-[#1f2937]',
  primary: 'bg-[#e5e7eb] text-[#1f2937]',
}

const sizeStyles: Record<NonNullable<BadgeProps['size']>, string> = {
  sm: 'px-2 py-0.5 text-xs rounded-[4px]',
  md: 'px-3 py-1   text-sm rounded-[4px]',
}

export default function Badge({
  label,
  color     = 'default',
  size      = 'md',
  className = '',
}: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center font-medium
        ${colorStyles[color]} ${sizeStyles[size]} ${className}`}
    >
      {label}
    </span>
  )
}
