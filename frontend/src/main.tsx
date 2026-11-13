import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { RecoveryBoundary, RequestStatus } from './components/layout/RecoveryBoundary';
import './index.css';
import 'katex/dist/katex.min.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RecoveryBoundary><App /><RequestStatus /></RecoveryBoundary>
  </React.StrictMode>
);
