import { useState } from "react";
import { LogOut, Menu, UserCircle } from "lucide-react";
import { navItems } from "./data";
import { NewbroLogo } from "./visual";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "../ui/sheet";

export type PageId = "Home" | "Bros" | "Nodes" | "Settings";

export function Sidebar({
  activePage,
  onNavigate,
  broCount,
  nodeCount,
  accountLabel,
  accountId,
  onLogout,
  logoutPending = false,
}: {
  activePage: PageId;
  onNavigate: (page: PageId) => void;
  broCount: number;
  nodeCount: number;
  accountLabel: string;
  accountId?: string | null;
  onLogout: () => void;
  logoutPending?: boolean;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  function navigate(page: PageId) {
    onNavigate(page);
    setDrawerOpen(false);
  }

  function handleLogout() {
    setDrawerOpen(false);
    onLogout();
  }

  function renderAccount(testId: string) {
    return (
    <div className="rounded-xl border border-[#e5e7eb] bg-[#f1f3f5] p-2.5">
      <div className="flex items-center gap-2.5">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white text-[#6b7280]">
          <UserCircle className="h-5 w-5" strokeWidth={1.9} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-semibold text-[#111827]">{accountLabel}</div>
          {accountId ? <div className="truncate text-[11px] text-[#9ca3af]">{accountId}</div> : null}
        </div>
      </div>
      <button
        type="button"
        data-testid={testId}
        disabled={logoutPending}
        onClick={handleLogout}
        className="mt-2 flex min-h-[36px] w-full items-center justify-center gap-2 rounded-lg border border-[#e5e7eb] bg-white px-3 text-[12px] font-semibold text-[#6b7280] transition hover:bg-[#fafafa] hover:text-[#111827] disabled:cursor-not-allowed disabled:opacity-60"
      >
        <LogOut className="h-3.5 w-3.5" strokeWidth={2} />
        {logoutPending ? "Logging out..." : "Log out"}
      </button>
    </div>
    );
  }

  const nav = (
    <nav className="flex w-full flex-col gap-0.5 text-[14px] lg:mt-2">
      {navItems.map((item) => {
        const Icon = item.icon;
        const isActive = item.label === activePage;
        const badgeValue = item.label === "Bros" ? broCount : item.label === "Nodes" ? nodeCount : null;
        return (
          <button
            key={item.label}
            type="button"
            onClick={() => navigate(item.label as PageId)}
            className={`group flex min-h-[40px] w-full items-center gap-2.5 rounded-lg px-2.5 text-left font-medium transition hover:bg-[#f1f3f5] hover:text-[#111827] ${
              isActive
                ? "bg-[#fff0ec] text-[#ff6a3d]"
                : "text-[#6b7280]"
            }`}
          >
            <Icon className="h-4 w-4 shrink-0" strokeWidth={1.9} />
            <span className="text-[13.5px]">{item.label}</span>
            {badgeValue !== null ? (
              <span className={`ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                isActive ? "bg-[#ff6a3d]/15 text-[#ff6a3d]" : "bg-[#f1f3f5] text-[#6b7280]"
              }`} aria-hidden="true">
                {badgeValue}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );

  return (
    <>
      <header
        data-testid="newbro-mobile-header"
        className="sticky top-0 z-40 flex min-h-[64px] w-full items-center justify-between border-b border-[#e5e7eb] bg-white/95 px-4 py-3 backdrop-blur lg:hidden"
      >
        <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
          <SheetTrigger asChild>
            <button
              type="button"
              aria-label="Open navigation menu"
              className="grid min-h-[44px] min-w-[44px] place-items-center rounded-lg border border-[#e5e7eb] bg-white text-[#6b7280] transition hover:bg-[#f1f3f5] hover:text-[#111827]"
            >
              <Menu className="h-5 w-5" strokeWidth={1.9} />
            </button>
          </SheetTrigger>
          <SheetContent
            side="left"
            className="w-[min(86vw,340px)] gap-6 border-[#e5e7eb] bg-white px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-5"
          >
            <SheetHeader className="pr-10">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <SheetDescription className="sr-only">
                Choose a Newbro workspace page.
              </SheetDescription>
              <NewbroLogo />
            </SheetHeader>
            {nav}
            <div className="mt-auto">{renderAccount("mobile-sidebar-logout")}</div>
          </SheetContent>
        </Sheet>
        <NewbroLogo />
      </header>

      <aside
        data-testid="newbro-sidebar"
        className="relative z-20 hidden w-full shrink-0 flex-col border-b border-[#e5e7eb] bg-white px-4 py-5 sm:px-5 lg:flex lg:min-h-dvh lg:w-[248px] lg:border-b-0 lg:border-r"
      >
        <div className="flex w-full flex-col">
          <NewbroLogo />
          <div className="mt-7 px-2 text-[10px] font-medium uppercase tracking-normal text-[#9ca3af]">Workspace</div>
          {nav}
        </div>

        <div className="mt-auto hidden lg:block">
          {renderAccount("sidebar-logout")}
        </div>
      </aside>
    </>
  );
}
