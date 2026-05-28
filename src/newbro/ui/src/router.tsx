import { useEffect, useState } from "react";
import { createRoute, createRouter, useNavigate, useSearch } from "@tanstack/react-router";
import { ArtboardBroDetailPage, ArtboardHomePage, ArtboardMobilePage } from "./ArtboardShell";
import { Route as rootRoute } from "./routes/__root";

function useIsMobile(): boolean {
  const query = "(max-width: 767px)";
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);
  return isMobile;
}

function useBroNavigate() {
  const navigate = useNavigate();
  const currentSearch = useSearch({ strict: false });
  return (broId: string) => {
    void navigate({
      to: "/bros/$broId",
      params: { broId },
      search: currentSearch,
    });
  };
}

function HomeRouteComponent() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const currentSearch = useSearch({ strict: false });
  const openBro = useBroNavigate();
  if (window.location.pathname !== "/") return null;
  if (isMobile) {
    return (
      <ArtboardMobilePage
        onOpenBro={openBro}
        onBack={() => { void navigate({ to: "/", search: currentSearch }); }}
      />
    );
  }
  return <ArtboardHomePage onOpenBro={openBro} />;
}

function BroDetailRouteComponent() {
  const params = broDetailRoute.useParams();
  const navigate = useNavigate();
  const currentSearch = useSearch({ strict: false });
  const isMobile = useIsMobile();
  const openBro = useBroNavigate();
  const goHome = () => { void navigate({ to: "/", search: currentSearch }); };
  if (isMobile) {
    return (
      <ArtboardMobilePage
        key={params.broId}
        broId={params.broId}
        onOpenBro={openBro}
        onBack={goHome}
      />
    );
  }
  return <ArtboardBroDetailPage broId={params.broId} onHome={goHome} />;
}

function MobileRouteComponent() {
  const [broId, setBroId] = useState<string | null>(null);
  return (
    <ArtboardMobilePage
      broId={broId}
      onOpenBro={setBroId}
      onBack={() => setBroId(null)}
    />
  );
}

function RemovedRouteComponent() {
  return null;
}

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomeRouteComponent,
});

const broDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/bros/$broId",
  component: BroDetailRouteComponent,
});

const mobileRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/mobile",
  component: MobileRouteComponent,
});

const removedBrosRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/bros",
  component: RemovedRouteComponent,
});

const removedNodesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/nodes",
  component: RemovedRouteComponent,
});

const removedSettingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: RemovedRouteComponent,
});

const routeTree = rootRoute.addChildren([
  homeRoute,
  broDetailRoute,
  mobileRoute,
  removedBrosRoute,
  removedNodesRoute,
  removedSettingsRoute,
]);

export function getRouter() {
  return createRouter({
    routeTree,
    defaultPreload: "intent",
    defaultErrorComponent: () => null,
    defaultNotFoundComponent: () => null,
    scrollRestoration: false,
  });
}
