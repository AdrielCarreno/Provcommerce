import './globals.css';
import type { Metadata } from 'next';
export const metadata: Metadata = {title:'Provcommerce | Inteligencia para comprar mejor',description:'Investigación de productos y proveedores para equipos B2B.'};
export default function Layout({children}:{children:React.ReactNode}) {return <html lang="es"><body>{children}</body></html>}
