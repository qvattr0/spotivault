import { CalendarClock, Disc3, History, LayoutDashboard, LibraryBig, MonitorPlay, Settings } from 'lucide-react';
import { NavLink } from 'react-router';
import { Brand } from '@/components/ui-a';
import { SidebarStatus } from './SidebarStatus.tsx';
import styles from './Sidebar.module.css';

/** The entries, in web-ui.md § Navigation's order, with components.md's icons. */
const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/library', label: 'Library', icon: LibraryBig },
  { to: '/albums', label: 'Albums', icon: Disc3 },
  { to: '/history', label: 'History', icon: History },
  { to: '/schedule', label: 'Schedule', icon: CalendarClock },
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/player', label: 'Player', icon: MonitorPlay },
];

/** The left sidebar of every app page (components.md § Sidebar, EPlEP). */
export function Sidebar() {
  return (
    <div className={styles.sidebar}>
      {/* Logo/Mark 32, not the drawing's resized Logo/Mark 64 (components.md § Differences, row 1). */}
      <div className={styles.brand}>
        <Brand variant="sidebar" className={styles.brandName} />
      </div>
      <nav aria-label="Main">
        <ul className={styles.nav}>
          {NAV.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              {/* Active on the page and the pages under it: /library/:id keeps Library lit. */}
              <NavLink to={to} className={styles.navItem}>
                <Icon size={22} />
                <span className={styles.label}>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className={styles.spacer} />
      <div className={styles.status}>
        <SidebarStatus />
      </div>
    </div>
  );
}
