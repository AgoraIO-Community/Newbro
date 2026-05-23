import { createRoute, createRouter, useNavigate, useSearch } from "@tanstack/react-router";
import type { PageId } from "./components/newbro";
import { DefaultCatchBoundary } from "./components/DefaultCatchBoundary";
import { NotFound } from "./components/NotFound";
import {
  BroDetailShellPage,
  BrosShellPage,
  HomeShellPage,
  MobileWalkieShellPage,
  NodesShellPage,
  SettingsShellPage,
} from "./NewbroShell";
import { Route as rootRoute } from "./routes/__root";

function pageToPath(page: PageId): "/" | "/bros" | "/nodes" | "/settings" {
  if (page === "Bros") return "/bros";
  if (page === "Nodes") return "/nodes";
  if (page === "Settings") return "/settings";
  return "/";
}

function usePageNavigate() {
  const navigate = useNavigate();
  const currentSearch = useSearch({ strict: false });
  return (page: PageId) => {
    void navigate({
      to: pageToPath(page),
      search: currentSearch,
    });
  };
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
  return <HomeShellPage onNavigate={usePageNavigate()} onBroNavigate={useBroNavigate()} />;
}

function BroDetailRouteComponent() {
  const params = broDetailRoute.useParams();
  return <BroDetailShellPage broId={params.broId} onNavigate={usePageNavigate()} />;
}

function BrosRouteComponent() {
  return <BrosShellPage onNavigate={usePageNavigate()} />;
}

function NodesRouteComponent() {
  return <NodesShellPage onNavigate={usePageNavigate()} />;
}

function SettingsRouteComponent() {
  return <SettingsShellPage onNavigate={usePageNavigate()} />;
}

function MobileRouteComponent() {
  return <MobileWalkieShellPage />;
}

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomeRouteComponent,
});

const brosRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/bros",
  component: BrosRouteComponent,
});

const broDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/bros/$broId",
  component: BroDetailRouteComponent,
});

const nodesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/nodes",
  component: NodesRouteComponent,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: SettingsRouteComponent,
});

const mobileRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/mobile",
  component: MobileRouteComponent,
});

const routeTree = rootRoute.addChildren([
  homeRoute,
  brosRoute,
  broDetailRoute,
  nodesRoute,
  settingsRoute,
  mobileRoute,
]);

export function getRouter() {
  return createRouter({
    routeTree,
    defaultPreload: "intent",
    defaultErrorComponent: DefaultCatchBoundary,
    defaultNotFoundComponent: () => <NotFound />,
    scrollRestoration: false,
  });
}
