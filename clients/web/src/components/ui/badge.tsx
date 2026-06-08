import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center justify-center gap-1 rounded-full px-2.5 py-1 text-[0.68rem] font-bold uppercase tracking-[0.16em]",
  {
    variants: {
      variant: {
        default: "bg-[rgba(18,144,122,0.12)] text-[#12907a]",
        secondary:
          "bg-white/80 text-[#5e6d66] shadow-[inset_0_0_0_1px_rgba(30,41,59,0.12)]",
        success: "bg-[rgba(16,185,129,0.12)] text-[#15795b]",
        warning: "bg-[rgba(245,158,11,0.14)] text-[#a16207]",
        destructive: "bg-[rgba(225,29,72,0.12)] text-[#9f1239]",
        outline: "text-[#1a2a23] shadow-[inset_0_0_0_1px_rgba(30,41,59,0.12)]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
