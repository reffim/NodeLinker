import axios from "axios"

const client = axios.create({
  baseURL: "/api/v1",
  withCredentials: true, // send HttpOnly auth cookies
  headers: { "Content-Type": "application/json" },
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      // Redirect to login on auth failure
      window.location.href = "/login"
    }
    return Promise.reject(err)
  }
)

export default client
