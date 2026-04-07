import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

function Sidebar() {
  const location = useLocation();
  return (
    <div className="sidebar">
      <h1>IoT Analytics</h1>
      <div className="nav-links">
        <Link to="/" className={`nav-link ${location.pathname === '/' ? 'active' : ''}`}>Dashboard</Link>
        <Link to="/management" className={`nav-link ${location.pathname === '/management' ? 'active' : ''}`}>Sensors</Link>
        <Link to="/benchmark" className={`nav-link ${location.pathname === '/benchmark' ? 'active' : ''}`}>Benchmarks</Link>
      </div>
    </div>
  );
}

function Dashboard() {
  const [sensors, setSensors] = useState([]);
  const [selectedSensor, setSelectedSensor] = useState('');
  const [chartData, setChartData] = useState([]);

  useEffect(() => {
    fetch('/api/sensors')
      .then(r => r.json())
      .then(data => {
        setSensors(data);
        if (data.length > 0 && !selectedSensor) {
          setSelectedSensor(data[0].logical_id);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedSensor) return;
    const fetchData = async () => {
      try {
        const res = await fetch(`/api/sensors/${selectedSensor}/data`);
        const json = await res.json();
        
        if (json.data && json.data.length > 0) {
           const formatted = json.data.slice(0, 300).map((d, i) => ({
             time: i,
             reading: parseFloat(d.reading).toFixed(4)
           }));
           setChartData(formatted);
        } else if (json.data_sample) { 
           const formatted = json.data_sample.slice(0, 300).map((val, i) => ({
             time: i,
             reading: parseFloat(val).toFixed(4)
           }));
           setChartData(formatted);
        }
      } catch (e) { console.warn(e); }
    };
    
    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, [selectedSensor]);

  return (
    <div>
      <h2 className="page-title">Live Telemetry Dashboard</h2>
      <div className="glass-panel">
        <div style={{ marginBottom: '20px' }}>
          <select 
             style={{ padding: '12px', background: 'rgba(0,0,0,0.5)', color: '#00e5ff', border: '1px solid #00e5ff', borderRadius: '8px', fontSize: '1rem', cursor: 'pointer' }}
             value={selectedSensor} 
             onChange={(e) => setSelectedSensor(e.target.value)}
          >
            <option value="" disabled>Select Target Modality...</option>
            {sensors.map(s => <option key={s.logical_id} value={s.logical_id}>{s.logical_id} / Physical: {s.hardware_id}</option>)}
          </select>
        </div>
        <div style={{ height: '500px', width: '100%' }}>
          <ResponsiveContainer>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="time" stroke="#8b92a5" tick={{ fill: '#8b92a5' }} />
              <YAxis stroke="#8b92a5" tick={{ fill: '#8b92a5' }} />
              <Tooltip contentStyle={{ backgroundColor: 'rgba(15, 17, 26, 0.95)', border: '1px solid rgba(0, 229, 255, 0.2)', borderRadius: '8px', color: '#fff' }} />
              <Line type="monotone" dataKey="reading" stroke="#00e5ff" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function Management() {
  const [sensors, setSensors] = useState([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [currentLogicalId, setCurrentLogicalId] = useState('');
  const [newHardwareId, setNewHardwareId] = useState('');

  const fetchSensors = () => fetch('/api/sensors').then(r => r.json()).then(setSensors).catch(()=>{});

  useEffect(() => { fetchSensors(); }, []);

  const handleRemap = async (e) => {
    e.preventDefault();
    await fetch('/api/sensors/remap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ logical_id: currentLogicalId, new_hardware_id: newHardwareId })
    });
    setModalOpen(false);
    fetchSensors();
  };

  return (
    <div>
      <h2 className="page-title">Sensor Fleet Management</h2>
      <div className="glass-panel">
        <table>
          <thead>
            <tr>
              <th>Logical Mapping</th>
              <th>Physical MAC/Hardware ID</th>
              <th>State</th>
              <th>Last Handshake</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {sensors.map(s => (
              <tr key={s.logical_id}>
                <td style={{ color: '#00e5ff' }}><strong>{s.logical_id}</strong></td>
                <td><code>{s.hardware_id}</code></td>
                <td>
                  <span className={`status-indicator ${s.online ? 'status-online' : 'status-offline'}`}></span>
                  {s.online ? 'Active' : 'Offline'}
                </td>
                <td>{new Date(s.updated_at).toLocaleString()}</td>
                <td>
                  <button className="btn" onClick={() => {
                    setCurrentLogicalId(s.logical_id);
                    setNewHardwareId('');
                    setModalOpen(true);
                  }}>Hot Swap ID</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {modalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3 style={{ color: '#00e5ff' }}>Initialize Hardware Substitution</h3>
            <form onSubmit={handleRemap}>
              <div className="form-group">
                <label>Semantic Target</label>
                <input type="text" value={currentLogicalId} disabled style={{ opacity: 0.5 }} />
              </div>
              <div className="form-group">
                <label>New Physical ID string</label>
                <input type="text" value={newHardwareId} onChange={e => setNewHardwareId(e.target.value)} required autoFocus placeholder="e.g., node_ac:44:fa" />
              </div>
              <div className="modal-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setModalOpen(false)}>Abort</button>
                <button type="submit" className="btn">Apply Bridge</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function Benchmarks() {
  const [results, setResults] = useState([]);
  
  useEffect(() => {
    fetch('/api/benchmark/results').then(r => r.json()).then(setResults).catch(()=>{});
  }, []);

  return (
    <div>
      <h2 className="page-title">TSDB Vector Evaluations</h2>
      <div className="glass-panel">
        <table>
          <thead>
            <tr>
              <th>Architecture Engine</th>
              <th>Simulation Limit</th>
              <th>Raw Burst Payload</th>
              <th>Volumetric Weight</th>
              <th>Sustained Trajectory</th>
              <th>Density Load</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => (
              <tr key={i}>
                <td style={{ color: r.database === 'clickhouse' ? '#2ed573': 'inherit' }}><strong>{r.database.toUpperCase()}</strong></td>
                <td>{r.sensors} Threads</td>
                <td>{r.raw_data_mb} MB</td>
                <td>{r.volume_size_mb} MB</td>
                <td>{parseFloat(r.rows_per_sec).toLocaleString()} TPS</td>
                <td>{r.overhead_ratio}x Ext.</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-container">
        <Sidebar />
        <div className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/management" element={<Management />} />
            <Route path="/benchmark" element={<Benchmarks />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
