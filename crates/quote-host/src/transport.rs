//! Bound connections before TLS handshakes and retain permits through HTTP IO.
use axum_server::accept::Accept;
use std::{
    future::Future,
    io,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};
use tokio::{
    io::{AsyncRead, AsyncWrite, ReadBuf},
    sync::{OwnedSemaphorePermit, Semaphore},
};
#[derive(Clone)]
pub struct Capacity<A> {
    pub inner: A,
    pub slots: Arc<Semaphore>,
}
pub struct Leased<T> {
    inner: T,
    _permit: OwnedSemaphorePermit,
}
impl<T: AsyncRead + Unpin> AsyncRead for Leased<T> {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_read(cx, buf)
    }
}
impl<T: AsyncWrite + Unpin> AsyncWrite for Leased<T> {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.inner).poll_write(cx, buf)
    }
    fn poll_write_vectored(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffers: &[io::IoSlice<'_>],
    ) -> Poll<io::Result<usize>> {
        Pin::new(&mut self.inner).poll_write_vectored(cx, buffers)
    }
    fn is_write_vectored(&self) -> bool {
        self.inner.is_write_vectored()
    }
    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_flush(cx)
    }
    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(&mut self.inner).poll_shutdown(cx)
    }
}
impl<A, I, S> Accept<I, S> for Capacity<A>
where
    A: Accept<I, S>,
    A::Stream: Send + Unpin + 'static,
    A::Service: Send + 'static,
    A::Future: Send + 'static,
{
    type Stream = Leased<A::Stream>;
    type Service = A::Service;
    type Future = Pin<Box<dyn Future<Output = io::Result<(Self::Stream, Self::Service)>> + Send>>;
    fn accept(&self, stream: I, service: S) -> Self::Future {
        let permit = self.slots.clone().try_acquire_owned();
        let future = self.inner.accept(stream, service);
        Box::pin(async move {
            let permit = permit.map_err(|_| io::Error::other("CONNECTION_CAPACITY"))?;
            let (stream, service) = future.await?;
            Ok((
                Leased {
                    inner: stream,
                    _permit: permit,
                },
                service,
            ))
        })
    }
}
