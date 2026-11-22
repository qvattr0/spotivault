import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';
import './styles/global.ts';
import { addFavicons } from './favicons.ts';
import { routes } from './routes.tsx';
import { liveStore } from '@/state';

addFavicons();

// One WebSocket for the whole app (WS /api/events). The hooks in @/state read what it brings.
liveStore.connect();

const router = createBrowserRouter(routes);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
