import { createRoute, createRouter, useNavigate, useSearch } from "@tanstack/react-router";
import { ArtboardBroDetailPage, ArtboardHomePage, ArtboardMobilePage } from "./ArtboardShell";
import { Route as rootRoute } from "./routes/__root";

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
  if (window.location.pathname !== "/") return null;
  return <ArtboardHomePage onOpenBro={useBroNavigate()} />;
}

function BroDetailRouteComponent() {
  const params = broDetailRoute.useParams();
  const navigate = useNavigate();
  const currentSearch = useSearch({ strict: false });
  return (
    <ArtboardBroDetailPage
      broId={params.broId}
      onHome={() => {
        void navigate({ to: "/", search: currentSearch });
      }}
    />
  );
}

function MobileRouteComponent() {
  return <ArtboardMobilePage />;
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
