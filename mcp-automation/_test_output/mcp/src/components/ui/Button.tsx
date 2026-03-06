import React from 'react'

export type ButtonProps = {
  variant?:   'primary' | 'secondary' | 'ghost'
  size?:      'sm' | 'md' | 'lg'
  children?:  React.ReactNode
  onClick?:   () => void
  disabled?:  boolean
  className?: string
}

const variantStyles: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary:   'bg-[#1a73e8] text-white hover:opacity-90 active:opacity-80',
  secondary: 'border border-[#1a73e8] text-[#1a73e8] bg-transparent hover:bg-[#1a73e8]/10',
  ghost:     'bg-transparent text-[#1a73e8] hover:bg-[#1a73e8]/10',
}

const sizeStyles: Record<NonNullable<ButtonProps['size']>, string> = {
  sm: 'h-[30px] px-3 text-sm   rounded-[6px]',
  md: 'h-[40px] px-4 text-base  rounded-[6px]',
  lg: 'h-[50px] px-6 text-lg    rounded-[6px]',
}

export default function Button({
  variant   = 'primary',
  size      = 'md',
  children,
  onClick,
  disabled  = false,
  className = '',
}: ButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center font-medium
        transition-opacity select-none
        ${variantStyles[variant]} ${sizeStyles[size]}
        ${disabled ? 'opacity-50 cursor-not-allowed pointer-events-none' : ''}
        ${className}`}
    >
      {children}
    </button>
  )
}
