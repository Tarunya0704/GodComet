export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="container mx-auto px-4 py-16">
        <div className="text-center">
          <h1 className="text-5xl font-bold text-gray-900 mb-6">
            Welcome to Your Website
          </h1>
          <p className="text-xl text-gray-600 mb-8">
            Generated from Figma design
          </p>
          <div className="flex gap-4 justify-center">
            <button className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-blue-600 transition">
              Get Started
            </button>
            <button className="px-6 py-3 border-2 border-primary text-primary rounded-lg hover:bg-blue-50 transition">
              Learn More
            </button>
          </div>
        </div>
        
        <div className="grid md:grid-cols-3 gap-8 mt-16">
          <div className="bg-white p-6 rounded-lg shadow-lg">
            <h3 className="text-xl font-semibold mb-3">Feature One</h3>
            <p className="text-gray-600">Amazing functionality that helps users achieve their goals.</p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow-lg">
            <h3 className="text-xl font-semibold mb-3">Feature Two</h3>
            <p className="text-gray-600">Powerful tools to streamline your workflow.</p>
          </div>
          <div className="bg-white p-6 rounded-lg shadow-lg">
            <h3 className="text-xl font-semibold mb-3">Feature Three</h3>
            <p className="text-gray-600">Intuitive interface for seamless experience.</p>
          </div>
        </div>
      </div>
    </main>
  )
}
