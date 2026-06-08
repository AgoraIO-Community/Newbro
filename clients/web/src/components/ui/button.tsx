import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[0_18px_40px_-24px_rgba(47,108,243,0.45)] hover:-translate-y-px hover:bg-[#245fe5]",
        secondary:
          "border border-border/70 bg-white/78 text-foreground shadow-[0_16px_40px_-30px_rgba(15,23,42,0.18),inset_0_1px_0_rgba(255,255,255,0.9)] backdrop-blur-md hover:-translate-y-px hover:bg-white/92",
        ghost: "text-muted-foreground hover:bg-white/68 hover:text-foreground",
        outline:
          "bg-transparent text-foreground shadow-[inset_0_0_0_1px_hsl(var(--border))] hover:bg-white/70",
        destructive: "bg-[#51423d] text-white hover:-translate-y-px hover:bg-[#433732]",
      },
      size: {
        default: "min-h-10 px-4 py-2",
        sm: "min-h-8 px-3 py-2 text-[0.78rem]",
        lg: "min-h-11 px-5 py-3",
        icon: "h-10 w-10 px-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
