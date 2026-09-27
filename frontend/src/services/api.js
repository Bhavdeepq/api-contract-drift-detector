import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
})

export const checkBackendHealth = () => api.get('/health')
export const getContracts = () => api.get('/api/contracts')
export const analyzeContract = selection => api.post('/api/analysis', selection)
export const createRemediationPlan = () => api.post('/api/remediation')
